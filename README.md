# powersaver #

A python power saving script for Linux HTPC/Homeserver running XBMC.

## Requirements ##

This script utilizes the following command line tools

* nslookup
* smbstatus
* rtcwake
* tail
* netstat

## Installation ##

Use crontab */etc/crontab* to schedule the script. My setting is to run it every 15 minutes such that the HTPC shuts down if not in use.

    # Powersaver
    */15 * * * * root /home/alex/powersaver/powersave.py
