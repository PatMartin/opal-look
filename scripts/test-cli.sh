#!/bin/bash

source .venv/Scripts/activate

# Test the CLI
opal-look-cli --help

# cam.json
echo '{
    "id":"side-eye",
    "name":"Side Eye",
    "kind":"rtsp",
    "locator":"rtsp://192.168.1.237:554/stream1"
}' > side-eye.json
opal-look-cli sources add --file side-eye.json
opal-look-cli sources list
opal-look-cli sources list --json
opal-look-cli sources show side-eye
opal-look-cli sources status side-eye
opal-look-cli sources probe side-eye
opal-look-cli sources delete side-eye