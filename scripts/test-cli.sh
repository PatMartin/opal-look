#!/bin/bash

source .venv/Scripts/activate

# Test the CLI
opal-look --help

# cam.json
echo '{
    "id":"side-eye",
    "name":"Side Eye",
    "kind":"rtsp",
    "locator":"rtsp://192.168.1.237:554/stream1"
}' > side-eye.json
opal-look sources add --file side-eye.json
opal-look sources list
opal-look sources list --json
opal-look sources show side-eye
opal-look sources status side-eye
opal-look sources probe side-eye
opal-look sources delete side-eye