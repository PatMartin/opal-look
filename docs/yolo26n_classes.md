# yolo26n — class labels

Class map for `yolo26n` (Ultralytics YOLO detection, COCO-pretrained),
extracted from the deployed weights via `model.names`
(`../opal-look-yolo/resources/models/yolo26n.pt`, ultralytics 8.4.213).

Detection results report `class_id` / `class_name`; `class_id` is the
index below, `class_name` the label. Standard COCO-80 vocabulary —
**80 classes**.

## Do classes differ by model? Yes — by task head

| Model variant | Task | Classes | Labels |
|---|---|---|---|
| `yolo26{n,s,m,l,x}` | detect | 80 | this table (COCO) |
| `-seg` | instance segmentation | 80 | same COCO labels + masks |
| `-obb` | oriented bounding box | 80 | same COCO labels, rotated boxes |
| `-pose` | pose estimation | 1 | `person` only + 17 keypoints |
| `-cls` | classification | 1000 | ImageNet (`tench`, `goldfish`, …) |
| `-depth` / `-sem` | depth / semantic seg | n/a | not class-based detectors |

Extract labels for any other weights file the same way:

```bash
cd ../opal-look-yolo
.venv/Scripts/python -c "from ultralytics import YOLO; \
    print(YOLO('resources/models/<model>.pt').names)"
```

## class_id → class_name

| id | class | id | class | id | class | id | class |
|---|---|---|---|---|---|---|---|
| 0 | person | 20 | elephant | 40 | wine glass | 60 | dining table |
| 1 | bicycle | 21 | bear | 41 | cup | 61 | toilet |
| 2 | car | 22 | zebra | 42 | fork | 62 | tv |
| 3 | motorcycle | 23 | giraffe | 43 | knife | 63 | laptop |
| 4 | airplane | 24 | backpack | 44 | spoon | 64 | mouse |
| 5 | bus | 25 | umbrella | 45 | bowl | 65 | remote |
| 6 | train | 26 | handbag | 46 | banana | 66 | keyboard |
| 7 | truck | 27 | tie | 47 | apple | 67 | cell phone |
| 8 | boat | 28 | suitcase | 48 | sandwich | 68 | microwave |
| 9 | traffic light | 29 | frisbee | 49 | orange | 69 | oven |
| 10 | fire hydrant | 30 | skis | 50 | broccoli | 70 | toaster |
| 11 | stop sign | 31 | snowboard | 51 | carrot | 71 | sink |
| 12 | parking meter | 32 | sports ball | 52 | hot dog | 72 | refrigerator |
| 13 | bench | 33 | kite | 53 | pizza | 73 | book |
| 14 | bird | 34 | baseball bat | 54 | donut | 74 | clock |
| 15 | cat | 35 | baseball glove | 55 | cake | 75 | vase |
| 16 | dog | 36 | skateboard | 56 | chair | 76 | scissors |
| 17 | horse | 37 | surfboard | 57 | couch | 77 | teddy bear |
| 18 | sheep | 38 | tennis racket | 58 | potted plant | 78 | hair drier |
| 19 | cow | 39 | bottle | 59 | bed | 79 | toothbrush |

## Practical notes for the camera feeds

- Relevant outdoors: `person`, `car`, `truck`, `bus`, `motorcycle`,
  `bicycle`, `cat`, `dog`, `bird`, `backpack`, `umbrella`.
- Filter server-side at predict/stream time with the `classes` engine
  option — e.g. `engine_options: {"classes": [0]}` restricts output to
  persons only:
  ```bash
  opal-look stream start <src> --name front-ai --engine yolo \
      --model yolo26n --options '{"classes": [0, 2, 15, 16]}'
  ```
- Everything else (e.g. "package", "face", "license plate") is **not**
  detectable by this model — that takes a fine-tuned or different-domain
  model dropped into `resources/models/`.
