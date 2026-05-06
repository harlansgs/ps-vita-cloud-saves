# Vita "cloud" saves server [VCS]

After configuration, all you have to do is open Vita Shell --> FTP on the desired Vita/TV consoles. This script will then connect to each, backup your saves directory, and push your most recent saves to out-of-sync devices. Only the most recent save files found will be shared to other Vita/TV devices, and a redundant set of backups are stored on the synchronization host to help prevent data loss.

Note that the script is intended to run as a daemon. Set this up on a Pi or old laptop and let it run. Then when you want to sync saves between your consoles, simply open VitaShell and enable FTP on each device you want to sync. The rest is done for you automatically.
- Notification of syncing is shown on the default dashboard page, but if you add your Twilio API key (free tier is fine) you can get SMS updates whenever sync is complete. These messages will include space remaining on the save synchronization host, and can optionally take a text in response to confirm prior to save sync. AWS keys can also be added for uploading backups to/from s3 for a true "cloud saves" integration.

Restrictions:
- this is designed for the case that all your devices are connected to the same network
- this is designed around the synchronization server always running -- you can just run the script when you need it but a cheap raspberry pi, old laptop, etc is recommended for a more painless "cloud saves" sort of functionality

### Default configuration reference

TODO

### How to add devices, handling synchronization paths

TODO
