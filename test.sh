#!/bin/sh
# Test the script output ISO against a proxmox server

./build_alpine_overlay.py --hostname boo
ssh root@pve qm stop 105
ssh root@pve rm /var/lib/vz/template/iso/boo_apkovl.iso
scp boo_apkovl.iso root@pve:/var/lib/vz/template/iso/.
ssh root@pve qm start 105
