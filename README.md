Introduction
============

Alpine Linux has the capability to do a 'headless' install without resorting to hacking of the original distributed ISO image.
That's right, you keep your ISO or Boot USB with the original download just as the developers intended, and then you provide a
supplementary media (DVD/USB or even Floppy disk) with a tarball overlay on it.  The contents of the tarball are extracted over
the initramfs prior to the login prompt, so if you craft the right files, you can run your own install automatically if 
an answerfile is included.  This utility provides those files plus a basic answerfile to run the install.  At the end of the
install it powers off.  Further setup can be conducted over ssh once the machine powers up again.  If you want to see what that looks
like, click on the video below:

[![Demo video](screenshot.png)](Alpine-Headless-Install.mov)


Requirements
============

- mkisofs (for generating the ISO image)
- Python3 (A basic Python install will do fine no fancy packages needed)
- SSH pub/private Keys must be present in `~/.ssh`, e.g. `ssh-keygen -t ed25519` the script will refuse to run without them.


Usage
=====

The output of the script is the ISO image.  The ISO image name always starts with the hostname, e.g. foo_apkovl.iso.  I enforced this
because I want to avoid multiple ISO overlay files in my Proxmox ISO store without knowing which is which!  I've allowed some options 
to be configurable, most of the time my VMs are using DHCP, so the only thing you really need is `--hostname`.  All other defaults are 
appropriate for Proxmox.

Very likely to work for you:

```
./build_alpine_overlay.py --hostname foo
```
...will generate two files:

```
alpine.apkovl.tar.gz     # In case you want to inspect the overlay files
foo_alkovl.iso           # What you make accessible to the machine at boot
```

There are some other flags to control the answer file, I rarely use them.

```
usage: build_alpine_overlay.py [-h] --hostname HOSTNAME [--out OUT] [--disk DISK] [--timezone TIMEZONE] [--keymap KEYMAP] [--devdopts DEVDOPTS] [--interfaces INTERFACES]

Build headless Alpine overlay ISO (apkovl inside)

options:
  -h, --help            show this help message and exit
  --hostname HOSTNAME   Target hostname
  --out OUT             Output ISO path suffix
  --disk DISK           Install disk device (e.g., /dev/sda or /dev/vda)
  --timezone TIMEZONE   Timezone (under /usr/share/zoneinfo)
  --keymap KEYMAP       Keymap layout and variant (e.g., 'us us' or 'none')
  --devdopts DEVDOPTS   Device manager option (e.g., 'mdev' or 'none'); default 'mdev' if omitted
  --interfaces INTERFACES
                        Full /etc/network/interfaces content; default DHCP template if omitted
```


Test Setup
==========

Here's a typical Proxmox setup for testing the generated ISO.  The script `test.sh` is used for trying out new Alpine versions.

![Screenshot](test-setup.png)


