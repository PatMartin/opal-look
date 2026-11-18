#!/bin/bash

cd /c/gh/opal/opal-look
source .venv/Scripts/activate

set -a && source .env && set +a
opal-look stream start "$OPAL_LOOK_FRONT_HI" --name front-hi
#opal-look stream start "$OPAL_LOOK_FRONT_LO" --name front-lo
#opal-look stream start "$OPAL_LOOK_SIDE_HI"  --name side-hi
#opal-look stream start "$OPAL_LOOK_SIDE_LO"  --name side-lo

ffplay -f mpjpeg "http://127.0.0.1:8002/api/v1/stream/front-hi/video"
