#!/usr/bin/env python
import re
from datetime import datetime, timedelta
from subprocess import Popen, PIPE
import urllib2, urllib
import json
import base64
import logging
import sys
import config

##############################
# PARSE ARGS - Set log level #
##############################
loglevel = logging.INFO
if len(sys.argv) > 1:
    if sys.argv[1] == "debug":
        loglevel = logging.DEBUG

logging.basicConfig(filename=config.logFile,
                    filemode='a',
                    level=loglevel,
                    format='%(asctime)s :: %(message)s',
                    datefmt='%b %d %H:%M:%S')

####################
# Helper functions #
####################

def xbmcCommand(method,params=None):
    # method as string
    # params as dictionary
    data = {"jsonrpc": "2.0",
                "id": "powersave script"}
    data['method'] = method
    if params != None:
        data['params'] = params
    # convert to json
    jsondata = json.dumps(data)
    # xbmc request
    xbmcUrl = "http://%s:%s/jsonrpc" % (config.xbmc['host'], config.xbmc['port'])
    req = urllib2.Request(url=xbmcUrl, data=jsondata, headers={'Content-Type': 'application/json'})
    base64string = base64.encodestring('%s:%s' % (config.xbmc['username'], config.xbmc['password'])).replace('\n', '')
    req.add_header("Authorization", "Basic %s" % base64string)
    response = urllib2.urlopen(req)
    result = json.loads(response.read())
    return result

def getHostname(ipaddress):
    host = Popen(['nslookup',ipaddress], stdout=PIPE)
    host = host.communicate(0)[0].split("\t")[-1].replace("\n","") # third line of nslookup command contains the desired information
    if "can't find" in host:
        return ipaddress
    else:
        host = re.search("name = ([\w\-]+)", host).group(1)
        return host

def getActiveSMBShares(ipaddress):
    smb = Popen(["smbstatus","-S"], stdout=PIPE, stderr=PIPE)
    smb = smb.communicate()[0].split("\n")
    smb = smb[3:-2]
    shares = []
    if len(smb) > 0:
        for line in smb:
            smbInfo = re.search('([\w$?]+)[\t ]+[\d]+[\t ]+(\d+\.\d+.\d+.\d+)', line) # extract connected Folder + IP address
            if smbInfo:
                if smbInfo.group(2) == ipaddress and smbInfo.group(1) != "IPC$":
                    shares.append(smbInfo.group(1))
    return shares

def getWakeTime(wakeTime):
    # wakeTime in 24h format string: "hh:mm"
    if wakeTime.split(':'):
        wake_hour = int(wakeTime.split(':')[0])
        wake_minute = int(wakeTime.split(':')[1])
    else:
        # Wrong wakeTime format
        return False
    # get current datetime
    now = datetime.now()
    wake = datetime(now.year, now.month, now.day, wake_hour, wake_minute)
    if now.time() < wake.time():
        # wakeTime is in the future on current day
        return int(wake.strftime('%s'))
    else:
        # wakeTime is in the past, so wake on next day
        wake += timedelta(days=1)
        return int(wake.strftime('%s'))

def setWakeUp(wakeTime):
    wtime = getWakeTime(wakeTime)
    rtc = Popen(["rtcwake","-m","no","-t %s" % wtime], stdout=PIPE, stderr=PIPE)
    rtc = rtc.communicate()
    if "wakeup" in rtc[0]:
        logging.info("Wake-up set to: %s." % datetime.fromtimestamp(wtime).strftime('%B %d, %H:%M') )
    else:
        logging.debug("ERROR setting up wake-up time!")
        for s in rtc:
            logging.debug("  " + s.replace('\n',''))

def pruneLog():
    lines = Popen(["tail","-n",str(config.logLines),config.logFile], stdout = PIPE)
    lines = lines.communicate()[0]
    with open(config.logFile, 'w') as prunedLog:
        prunedLog.write(lines)

def shutdown():
    if hasattr(config, 'wakeTime'):
        setWakeUp(config.wakeTime)
    xbmc = xbmcCommand("System.Shutdown")
    if "OK" in xbmc['result']:
       logging.info("Will shutdown now through XBMC.")
    else:
        logging.info("Will shutdown now using system command.")
        Popen(["shutdown","-h","now"])

###########
# Methods #
###########

def xbmcIsIdle():
    if not hasattr(config, 'xbmc'):
        return True
    xbmc = xbmcCommand("XBMC.GetInfoBooleans", {"booleans": ["System.ScreenSaverActive"]})
    if xbmc['result']['System.ScreenSaverActive']:
        logging.debug("XBMC screensaver is active.")
        return True
    else:
        logging.info("XBMC is or was in use.")
        return False

def xbmcIsPlaying():
    if not hasattr(config, 'xbmc'):
        return False
    xbmc = xbmcCommand("Player.GetActivePlayers")
    if len(xbmc['result']) > 0:
        playerid = xbmc['result'][0]['playerid']
        player = xbmcCommand("Player.GetItem", { "properties": ["title", "album", "artist", "season", "episode", "showtitle",], "playerid": playerid })
        item = player['result']['item']
        if item['type'] == 'movie':
            logging.info("XBMC is playing: %s" % item['title'])
        else:
            if item['type'] == 'episode':
                logging.info("XBMC is playing: %s S%02iE%02i - %s" % (item['showtitle'], item['season'], item['episode'], item['title']))
            else:
                logging.info("XBMC is playing: %s." % item['label'])
        return True
    else:
        logging.debug("XBMC is not playing.")
        return False

def activeConnections():
    active = False
    connections = Popen(["netstat","-tn"], stdout=PIPE, stderr=PIPE)
    connections = connections.communicate()[0].split("\n")
    # initialize empty active port dictionary to append active hosts to ports
    act = {}
    for port in config.services.keys():
        act[port] = []
    for line in connections:
        if any(port in line for port in config.services.keys()) and any(constring in line for constring in config.conKeys):
            conInfo = re.search(":([\d]+)[\t ]+(\d+\.\d+\.\d+\.\d+):", line)
            port = conInfo.group(1)
            host = conInfo.group(2)
            if port in act.keys():
                act[port].append(host)
    # iterate over active ports
    for port in act.keys():
        if len(act[port]) > 0:
            hosts = list(set(act[port])) # unique active hosts at this port
            if '127.0.0.1' in hosts:
                hosts.remove('127.0.0.1') # don't want to check for localhost
            for host in hosts:
                n = act[port].count(host) # number of connections to host at this port
                if port == "445": # samba connection, show mounted shares
                    shares = getActiveSMBShares(host)
                    sharesString = ", ".join(map(str, shares))
                    if len(shares) > 0:
                        active = True
                        logging.info("Found %i active %s share%s from %s: %s" % (len(shares),config.services[port], "s" if len(shares) > 1 else "", getHostname(host), sharesString))
                else:
                    active = True
                    logging.info("Found %i %s connection%s from %s." % (n,config.services[port], "s" if n > 1 else "", getHostname(host)))
    return active

def activeSABnzbd():
    if not hasattr(config, 'sabapi'):
        return False
    saburl = 'http://localhost:8080/sabnzbd/api'
    params = {'apikey': config.sabapi,
              'mode':   'qstatus',
              'output': 'json'}
    urldata = urllib.urlencode(params)
    req = urllib2.Request(url=saburl,data=urldata)
    response = urllib2.urlopen(req)
    result = json.loads(response.read())
    if result['state'] == u'IDLE':
        logging.debug("SABnzbd is IDLE. Checking history for processing jobs.")
        # do history check if processing is going on
        params = {'apikey': config.sabapi,
                  'mode':   'history',
                  'output': 'json',
                  'start':  0,
                  'limit':  1}
        urldata = urllib.urlencode(params)
        req = urllib2.Request(url=saburl,data=urldata)
        response = urllib2.urlopen(req)
        hresult = json.loads(response.read())
        job = hresult['history']['slots'][0]
        status = job['status']
        if status == u"Completed" or status == u"Failed":
            logging.debug("SABnzbd history is %s." % status)
            return False
        else:
            logging.info("SABnzbd is %s a download: %s" % (status, job['name']))
            return True
    if result['state'] == u'Downloading':
        for job in result['jobs']:
            progress = (job['mb']-job['mbleft']) / job['mb'] * 100
            logging.info("SABnzbd is downloading: %s [%.0f%%]" % (job['filename'], progress))
        return True
    if result['state'] == u'Paused':
        for job in result['jobs']:
            progress = (job['mb']-job['mbleft']) / job['mb'] * 100
            logging.info("SABnzbd is paused: %s [%.0f%%]" % (job['filename'], progress))
        return True


########
# MAIN #
########
if __name__ == '__main__':

    logging.info(":: :: :: :: :: :: :: :: :: :: ")

    XBMC_IDLE    = xbmcIsIdle()
    XBMC_PLAYING = xbmcIsPlaying()
    CON_ACTIVE   = activeConnections()
    SAB_ACTIVE   = activeSABnzbd()

    logging.debug("XBMC_IDLE:    %s" % XBMC_IDLE)
    logging.debug("XBMC_PLAY:    %s" % XBMC_PLAYING)
    logging.debug("CON_ACTIVE:   %s" % CON_ACTIVE)
    logging.debug("SAB_ACTIVE:   %s" % SAB_ACTIVE)

    pruneLog()

    if XBMC_IDLE and not XBMC_PLAYING and not CON_ACTIVE and not SAB_ACTIVE:
        shutdown()
