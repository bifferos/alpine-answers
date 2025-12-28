#!/usr/bin/env python3
"""
    Test the script output ISO against a proxmox server
"""

import re
import os
import shutil
import urllib3
import requests
from pathlib import Path
from pprint import pprint
from functools import lru_cache
import hashlib
import time
from subprocess import run, CalledProcessError


# Disable insecure request warnings, not needed for secure homelab environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# I put my Proxmox API credentials in this file
HOME_DIR = Path.home()
PROXMOD_DIR = HOME_DIR / ".proxmox"
API_FILE = PROXMOD_DIR / "api.ini"


TARBALL_FILE = Path("alpine.apkovl.tar.gz")
ISO_FILE = Path("headless_test_apkovl.iso")


if not API_FILE.exists():
    print("Error: Missing API configuration file.")
    print("Please create the file with the necessary API credentials.")
    raise FileNotFoundError(f"Requires API file at {API_FILE}")


def get_proxmox_token():
    from configparser import ConfigParser
    config = ConfigParser()
    config.read(API_FILE)
    token_id = config["default"]["TokenId"]
    secret = config["default"]["Secret"]
    return token_id, secret


class Proxmox:
    def __init__(self, host="pve", node="pve"):
        self.base = f"https://{host}:8006/api2/json"
        self.token_id, self.secret = get_proxmox_token()
        self.host = host
        self.node = node
        self.session = requests.Session()
        self.session.verify = False
        auth = f"PVEAPIToken {self.token_id}={self.secret}"
        print("Using auth:", auth)
        self.session.headers.update({
            "Authorization": auth
        })

    def get(self, path, params=None):
        response = self.session.get(f"{self.base}/{path}", params=params)
        response.raise_for_status()
        return response.json()["data"]
    
    def post(self, path, data=None):
        response = self.session.post(f"{self.base}/{path}", data=data)
        response.raise_for_status()
        return response.json()["data"]

    def delete(self, path, params=None):
        response = self.session.delete(f"{self.base}/{path}", params=params)
        response.raise_for_status()
        return response.json()["data"]


def wait_for_task(proxmox: "Proxmox", upid: str, poll_interval: float = 2.0, timeout: int = 600):
    """Poll the Proxmox task until it finishes; raise on failure or timeout."""
    start = time.time()
    while True:
        status = proxmox.get(f"nodes/{proxmox.node}/tasks/{upid}/status")
        st = status.get("status")
        if st == "stopped":
            exitstatus = status.get("exitstatus", "")
            print(f"Task {upid} finished: {exitstatus}")
            if exitstatus not in ("OK", "success", ""):
                raise RuntimeError(f"Task {upid} failed: {exitstatus}")
            return exitstatus
        if time.time() - start > timeout:
            raise TimeoutError(f"Task {upid} did not finish within {timeout}s")
        time.sleep(poll_interval)


@lru_cache()
def get_latest_alpine_iso_info():
    URL = "https://www.alpinelinux.org/downloads/"
    response = requests.get(URL)
    response.raise_for_status()
    html_content = response.text.splitlines()
    for line in html_content:
        m = re.search(r'alpine-standard-([0-9\.]+)-x86_64\.iso', line)
        if m:
            version = m.group(1)
            iso_name = f"alpine-standard-{version}-x86_64.iso"
            return iso_name, version

    raise ValueError("Failed to determine latest Alpine Linux ISO name")


def has_iso(proxmox: Proxmox, iso_name: str) -> bool:
    isos = proxmox.get(f"nodes/{proxmox.node}/storage/local/content", params={"content": "iso"})
    for iso in isos:
        if iso["volid"].endswith(iso_name):
            return True
    return False


def download_iso(iso_name: str, version: str):
    short_version = ".".join(version.split(".")[:2])
    download_url = f"https://dl-cdn.alpinelinux.org/alpine/v{short_version}/releases/x86_64/{iso_name}"
    sha_url = f"{download_url}.sha256"

    response = requests.get(sha_url)
    response.raise_for_status()
    sha256_expected = response.text.split()[0]
    print(sha256_expected)

    if Path(iso_name).exists():
        print(f"{iso_name} already exists, skipping download.")
        digest = hashlib.sha256()
        with open(iso_name, "rb") as f:
            while chunk := f.read(8192):
                digest.update(chunk)
        sha256_actual = digest.hexdigest()
        if sha256_actual != sha256_expected:
            print("Existing ISO checksum does not match expected, re-downloading.")
            os.remove(iso_name)
        else:
            print("Existing ISO checksum matches the expected value.")
            return

    print(f"Downloading ISO from {download_url}...")
    response = requests.get(download_url, stream=True)
    response.raise_for_status()
    with open(iso_name, "wb") as f:
        shutil.copyfileobj(response.raw, f)
    print(f"Downloaded {iso_name}")


def upload_iso_stream(proxmox: "Proxmox", iso_path: Path, storage: str = "local"):
    url = f"{proxmox.base}/nodes/{proxmox.node}/storage/{storage}/upload"
    with open(iso_path, "rb") as f:
        files = {
            # Field name must be 'filename' per Proxmox API
            "filename": (iso_path.name, f, "application/octet-stream"),
        }
        data = {"content": "iso"}
        resp = proxmox.session.post(url, files=files, data=data)
        if resp.status_code >= 400:
            try:
                print("Upload failed:", resp.status_code, resp.json())
            except Exception:
                print("Upload failed:", resp.status_code, resp.text[:2000])
            resp.raise_for_status()


def ensure_latest_alpine_in_iso_store(proxmox):
    iso_name, version = get_latest_alpine_iso_info()
    isos = proxmox.get(f"nodes/{proxmox.node}/storage/local/content", params={"content": "iso"})
    if has_iso(proxmox, iso_name):
        print(f"Latest ISO {iso_name} already present in Proxmox ISO store.")
    else:
        print("Latest ISO not found, downloading it...")
        download_iso(iso_name, version)

        print("Uploading ISO to Proxmox (streaming multipart, no yields)...")
        upload_iso_stream(proxmox, Path(iso_name), storage="local")
        print(f"Uploaded {iso_name} to Proxmox ISO store.")


def get_next_vmid(proxmox: "Proxmox") -> int:
    """Get the next free VMID from Proxmox (server-chosen)."""
    vmid_str = proxmox.get("cluster/nextid")
    return int(vmid_str)


def create_vm_with_iso(proxmox: "Proxmox", name: str, boot_iso: str):
    """Create a VM with the next free VMID and attach an ISO for install."""
    vmid = get_next_vmid(proxmox)
    data = {
        "vmid": vmid,
        "name": name,
        "ostype": "l26",
        "cores": 1,
        "memory": 2048,
        "net0": f"virtio,bridge=vmbr1",
        # Disk on SCSI with virtio-scsi controller
        "scsihw": "virtio-scsi-pci",
        "scsi0": f"local-lvm:16",
        # Attach ISO as CD-ROM on ide0
        "ide0": f"local:iso/{boot_iso},media=cdrom",
        # Attach ISO as CD-ROM on ide2
        "ide2": f"local:iso/{ISO_FILE.name},media=cdrom",
        # Boot from disk first, then CD-ROM
        "bootdisk": "scsi0",
        "boot": "order=scsi0;ide0",
        # Enable qemu-guest-agent if present
        "agent": 1,
    }
    upid = proxmox.post(f"nodes/{proxmox.node}/qemu", data=data)
    print(f"Created VM {name} with VMID {vmid}. Task: {upid}")
    wait_for_task(proxmox, upid)
    return vmid


def create_test_vm(proxmox, vm_name):
    iso_name, _ = get_latest_alpine_iso_info()
    vmid = create_vm_with_iso(proxmox, vm_name, iso_name)
    print(f"VM {vm_name} created with VMID {vmid}")
    return vmid


def start_test_vm(proxmox, vmid):
    print(f"Starting VMID {vmid}...")
    upid = proxmox.post(f"nodes/{proxmox.node}/qemu/{vmid}/status/start")
    print(f"Started VMID {vmid}. Task: {upid}")
    wait_for_task(proxmox, upid)


def wait_for_shutdown(proxmox, vmid):
    print(f"Waiting for VMID {vmid} to power off...")
    while True:
        status = proxmox.get(f"nodes/{proxmox.node}/qemu/{vmid}/status/current")
        if status.get("status") == "stopped":
            print(f"VMID {vmid} has powered off.")
            return
        time.sleep(5)


def delete_test_vm(proxmox, vm_name):
    find_vm_with_name = proxmox.get(f"nodes/{proxmox.node}/qemu")
    vmid = None
    for vm in find_vm_with_name:
        if vm["name"] == vm_name:
            vmid = vm["vmid"]
            break

    print(f"Found VMID {vmid} for VM name {vm_name}")

    # Delete VM via HTTP DELETE on the VM resource
    if vmid is None:
        print(f"No VM found with name {vm_name}, skipping delete.")
    else:
        print(f"Deleting VM {vm_name} with VMID {vmid}...")
        upid = proxmox.delete(f"nodes/{proxmox.node}/qemu/{vmid}")
        print(f"Deleted VM {vm_name}. Task: {upid}")
        wait_for_task(proxmox, upid)


def delete_iso_file(proxmox, iso_name):
    isos = proxmox.get(f"nodes/{proxmox.node}/storage/local/content", params={"content": "iso"})
    iso_found = False
    for iso in isos:
        if iso["volid"].endswith(iso_name):
            iso_found = True
            break

    if not iso_found:
        print(f"No ISO found with name {iso_name}, skipping delete.")
    else:
        print(f"Deleting ISO {iso_name}...")
        upid = proxmox.delete(f"nodes/{proxmox.node}/storage/local/content/{iso['volid']}")
        print(f"Deleted ISO {iso_name}. Task: {upid}")
        wait_for_task(proxmox, upid)


def cleanup(proxmox, vm_name):
    """Reset state before test run"""
    TARBALL_FILE.unlink(missing_ok=True)
    ISO_FILE.unlink(missing_ok=True)
    delete_test_vm(proxmox, vm_name)
    delete_iso_file(proxmox, ISO_FILE.name)


def main():
    proxmox = Proxmox("pve", "pve")
    vm_name = "alpine-headless-test"
    cleanup(proxmox, vm_name)
    run(["./build_alpine_overlay.py", "--hostname", vm_name, "--iso", str(ISO_FILE)], check=True)
    ensure_latest_alpine_in_iso_store(proxmox)
    upload_iso_stream(proxmox, ISO_FILE, storage="local")
    vmid = create_test_vm(proxmox, vm_name)
    start_test_vm(proxmox, vmid)
    time.sleep(10)
    wait_for_shutdown(proxmox, vmid)
    start_test_vm(proxmox, vmid)


if __name__ == "__main__":
    main()
