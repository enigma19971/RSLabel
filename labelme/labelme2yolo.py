#!/usr/bin/env python

from __future__ import print_function

import argparse
import glob
import json
import os
import os.path as osp

import numpy as np
import PIL.Image

import labelme


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('labels_file')
    parser.add_argument('in_dir', help='input dir with annotated files')
    parser.add_argument('out_dir', help='output dataset directory')
    args = parser.parse_args()

    if osp.exists(args.out_dir):
        print('Output directory already exists:', args.out_dir)
        quit(1)
    os.makedirs(args.out_dir)
    os.makedirs(osp.join(args.out_dir, 'images'))
    os.makedirs(osp.join(args.out_dir, 'labels'))
    os.makedirs(osp.join(args.out_dir, 'AnnotationsVisualization'))
    print('Creating dataset:', args.out_dir)

    class_names = []
    class_name_to_id = {}
    for i, line in enumerate(open(args.labels_file).readlines()):
        class_id = i - 1  # starts with -1
        class_name = line.strip()
        class_name_to_id[class_name] = class_id
        if class_id == -1:
            assert class_name == '__ignore__'
            continue
        elif class_id == 0:
            assert class_name == '_background_'
        class_names.append(class_name)
    class_names = tuple(class_names)
    print('class_names:', class_names)
    out_class_names_file = osp.join(args.out_dir, 'class_names.txt')
    with open(out_class_names_file, 'w') as f:
        f.writelines('\n'.join(class_names))
    print('*Saved class_names:', out_class_names_file)

    for label_file in glob.glob(osp.join(args.in_dir, '*.json')):
        print('Generating dataset from:', label_file)
        with open(label_file) as f:
            data = json.load(f)
        base = osp.splitext(osp.basename(label_file))[0]
        out_img_file = osp.join(
            args.out_dir, 'images', base + '.jpg')
        out_txt_file = osp.join(
            args.out_dir, 'labels', base + '.txt')
        out_viz_file = osp.join(
            args.out_dir, 'AnnotationsVisualization', base + '.jpg')

        img_file = osp.join(osp.dirname(label_file), data['imagePath'])
        img = np.asarray(PIL.Image.open(img_file))
        PIL.Image.fromarray(img).save(out_img_file)

        height, width = img.shape[:2]
        yololines = []

        bboxes = []
        labels = []
        for shape in data['shapes']:
            if shape['shape_type'] != 'rectangle':
                print('Skipping shape: label={label}, shape_type={shape_type}'
                      .format(**shape))
                continue

            class_name = shape['label']
            class_id = class_names.index(class_name)

            (xmin, ymin), (xmax, ymax) = shape['points']
          
            bboxes.append([xmin, ymin, xmax, ymax])
            labels.append(class_id)

            xc = (xmax + xmin) / 2 / width
            yc = (ymax + ymin) / 2 / height
            w = (xmax - xmin) / width
            h = (ymax - ymin) / height
            yololines.append(' '.join(map(str, (class_id, xc, yc, w, h))))

        captions = [class_names[l] for l in labels]
        viz = labelme.utils.draw_instances(
            img, bboxes, labels, captions=captions
        )
        PIL.Image.fromarray(viz).save(out_viz_file)

        with open(out_txt_file, 'w') as f:
            f.write('\n'.join(yololines))


if __name__ == '__main__':
    main()
