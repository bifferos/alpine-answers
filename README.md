Introduction
============

Alpine Linux has the capability to do a 'headless' install without resorting to hacking of the original distributed ISO image.
That's right, you keep your ISO or Boot USB with the original download just as the developers intended, and then you provide a
supplementary media (DVD/USB or even Floppy disk) with a tarball overlay on it.  The contents of the tarball are extracted over
the initramfs prior to the login prompt, so if you craft the right files, you can run your own install automatically if 
an answerfile is included.  This utility provides those files plus a basic answerfile to run the install.  At the end of the
install it powers off.  See:

[![Demo video](screenshot.png)](Alpine-Headless-Install.mov)


Requirements
============

- mkisofs (for generating the ISO image)
- Python3 (A basic Python install will do fine no fancy packages needed)
- SSH pub/private Keys must be present in `~/.ssh`, e.g. `ssh-keygen -t ed25519` the script will refuse to run without them.


Usage
=====

The output of the script is the ISO image.  

Very likely to work for you:

```
./build_alpine_overlay.py --hostname foo
```
...will generate two files:

```
alpine.apkovl.tar.gz     # In case you want to inspect the overlay files
apkovl.iso               # What you connect to your VM
```


Test Setup
==========

Here's a typical Proxmox setup for testing the generated ISO.  The script
`test.sh` is used for trying out new Alpine versions, it will create VM
like the one below.  It uses my pvectl utility to provision a VM on Proxmox.

![Screenshot](test-setup.png)


