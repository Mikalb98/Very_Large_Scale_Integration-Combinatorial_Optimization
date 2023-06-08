import glob
import json
import logging
import warnings
from argparse import ArgumentParser

from matplotlib import pyplot as plt
from matplotlib.patches import Rectangle
from z3 import *
import time
import os
import multiprocessing

import numpy as np


def get_heights(heights_folder, args):
    # define path and name of runtime file:
    file_name = f'SMT' \
                f'{"-sb" if args.symmetry_breaking else ""}' \
                f'{"-rot" if args.rotation else ""}' \
                f'.json'

    file_path = os.path.join(heights_folder, file_name)

    # if file exists load it and extract dict values, otherwise return empty dict:
    if os.path.isfile(file_path):
        with open(file_path) as f:

            # load dictionary:
            dictionary = json.load(f)
            data = {}

            for k, v in dictionary.items():
                int_key = int(k)
                data[int_key] = v
    else:
        data = {}

    return data, file_path


# creates and plots the colour map with rectangles:
def plot_board(width, height, blocks, rotation, instance, show_plot=False, show_axis=False, verbose=False):
    # suppress get_cmap warning
    warnings.filterwarnings('ignore', message="The get_cmap function was deprecated in Matplotlib 3.7")
    # define pyplot colour map of len(blocks) number of colours:
    cmap = plt.cm.get_cmap('jet', len(blocks))

    # define figure size:
    fig, ax = plt.subplots(figsize=(10, 10))

    # add each rectangle block in the colour map:
    for component, (w, h, x, y) in enumerate(blocks):
        label = f'{w}x{h}, ({x},{y})'

        if rotation is not None:
           label += f', R={1 if rotation[component] else 0}'

        ax.add_patch(
            Rectangle((x.as_long(), y.as_long()), w, h, facecolor=cmap(component), edgecolor='k', label=label, lw=2,
                      alpha=0.8))

    # set plot properties:
    ax.set_ylim(0, height)
    ax.set_xlim(0, width)
    ax.set_xlabel('width', fontsize=15)
    ax.set_ylabel('length', fontsize=15)
    ax.legend()
    ax.set_title(f'Instance {instance}, size (WxH): {width}x{height}', fontsize=22)

    # print axis if wanted:
    if not show_axis:
        ax.set_xticks([])
        ax.set_yticks([])

        # save colormap in .png format at given path:
        project_folder = os.path.abspath(os.path.join(os.getcwd(), "..", ".."))
        figure_path = os.path.join(project_folder, "SMT", "out", "rotation", "images", f"ins-{instance}.png")

        plt.savefig(figure_path)

        # check if file was saved at correct path:
        if verbose:
            if os.path.exists(figure_path):
                print(f"figure ins-{instance}.png has been correctly saved at path '{figure_path}'")

    # to show plot:
    if show_plot:
        plt.show(block=False)
        plt.pause(1)
    plt.close(fig)


def solve_instance_rot(instance, index, args):
    def max_z3(vars):
        maximum = vars[0]
        for v in vars[1:]:
            maximum = If(v > maximum, v, maximum)
        return maximum

    def min_z3(vars):
        min = vars[0]
        for v in vars[1:]:
            min = If(v < min, v, min)
        return min

    def real_dim(dim, dim_swap, rot, n):
        res = [If(rot[i], dim_swap[i], dim[i]) for i in range(n)]
        return res

    def cumulative_z3(start, duration, resources, total):
        c = []
        for u in resources:
            c.append(sum([If(And(start[i] <= u, u < start[i] + duration[i]), resources[i], 0)
                          for i in range(len(start))]) <= total)
        return c

    # initialize instance parameters
    n = instance['n']
    w = instance['w']
    widths = instance['inputx']
    heights = instance['inputy']
    minh = instance['minh']
    # maxh = instance['maxh']
    min_height = minh
    max_height = sum(heights)
    # max_height = sum([If(rotation_c[i], widths[i], heights[i]) for i in range(n)])

    # variables
    x = IntVector('x', n)
    y = IntVector('y', n)

    # array of booleans, each one telling if the corresponding chip is rotated or not
    rotation_c = BoolVector('r', n)

    # plate_height = max_z3([y[i] + heights[i] for i in range(n)])
    # plate_height = Int('plate_height' ) #z3

    # height that is going to be minimized from the optimizer

    plate_height = max_z3([If(rotation_c[i], widths[i], heights[i]) + y[i] for i in range(n)])

    big_circuit_idx = np.argmax([widths[i] * heights[i]
                                 for i in range(n)])

    # array of booleans, each one telling if the corresponding chip is rotated or not
    rotation_c = BoolVector('r', n)
    opt = Optimize()

    # Handle rotation
    '''
    if args.rotation:
        rotations = BoolVector("rotations", n)
        copy_widths = widths
        widths = [If(rotations[i], heights[i], widths[i])
                  for i in range(n)]
        heights = [If(rotations[i], copy_widths[i], heights[i])
                   for i in range(n)]
      '''

    # Bounds on variables
    # Plate height bounds
    opt.add(And(plate_height >= min_height, plate_height <= max_height))

    for i in range(n):

        # X and Y bounds
        opt.add(And(x[i] >= 0, x[i] <= w - min_z3(real_dim(widths, heights, rotation_c, n))))
        opt.add(And(y[i] >= 0, y[i] <= max_height - min_z3(real_dim(heights, widths, rotation_c, n))))

        # Main constraints
        opt.add(x[i] + If(rotation_c[i], heights[i], widths[i]) <= w)
        opt.add(y[i] + If(rotation_c[i], widths[i], heights[i]) <= plate_height)

        # Constraint to avoid rotation of square circuits
        opt.add(Implies(widths[i] == heights[i], Not(rotation_c[i])))

        # Constraint to avoid rotation of out of bound circuits
        opt.add(Implies(Or(widths[i] > max_height, heights[i] > w), Not(rotation_c[i])))

        for j in range(i + 1, n):
            # Non overlapping constraints
            opt.add(Or(x[i] + If(rotation_c[i], heights[i], widths[i]) <= x[j],
                       x[j] + If(rotation_c[j], heights[j], widths[j]) <= x[i],
                       y[i] + If(rotation_c[i], widths[i], heights[i]) <= y[j],
                       y[j] + If(rotation_c[j], widths[j], heights[j]) <= y[i]))

            # Ordering constraint between equal circuits
            opt.add(Implies(And(heights[i] == heights[j], widths[i] == widths[j]),
                            And(x[i] <= x[j], Implies(x[i] == x[j], y[i] < y[j]))))

    # Adding cumulative constraints
    # opt.add(cumulative_z3(x, widths, heights, plate_height))
    opt.add(cumulative_z3(y,
                          [If(rotation_c[i], widths[i], heights[i]) for i in range(n)],
                          [If(rotation_c[i], heights[i], widths[i]) for i in range(n)],
                          w))

    # Largest circuit in the origin
    opt.add(And(x[big_circuit_idx] == 0, y[big_circuit_idx] == 0))

    # SYM BREAK

    if True:  # args.symmetry_breaking:
        # find the indexes of the 2 largest pieces
        circuits_area = [widths[i] * heights[i] for i in range(n)]

        first_max = np.argsort(circuits_area)[-1]
        second_max = np.argsort(circuits_area)[-2]

        # the biggest circuit is always placed for first w.r.t. the second biggest one
        sb_biggest_lex_less = Or(x[first_max] < x[second_max],
                                 And(x[first_max] == x[second_max], y[first_max] <= y[second_max])
                                 )

        # width maggiore -> coord y < h/2
        # height maggiore -> coord x < w/2
        sb_biggest_in_first_quadrande = And(x[first_max] < w / 2, y[first_max] < plate_height / 2)

        # add constraint
        opt.add(sb_biggest_in_first_quadrande)
        opt.add(sb_biggest_lex_less)

    opt.minimize(plate_height)

    opt.set("timeout", 300 * 1000)  # 5 minutes timeout
    start_time = time.time()

    if opt.check() == sat:
        model = opt.model()
        print("Solving time (s): ", round(time.time() - start_time, 3))
        height = model.eval(plate_height).as_long()
        print("Height:", height)
        xs, ys, rot = [], [], []
        for i in range(n):
            xs.append(model.evaluate(x[i]))
            ys.append(model.evaluate(y[i]))
            rot.append(model.evaluate(rotation_c[i]))
            # if the i-th rectangle is rotated
            if model.evaluate(rotation_c[i]):
                print(f'rectangle {i} is rotated')
                # invert width and height of the i-th rectangle
                true_x, true_y = heights[i], widths[i]
                widths[i], heights[i] = true_x, true_y
        print("x:", xs)
        print("y:", ys)
        print(rot)
        # updates instance
        instance['h'] = height
        instance['xsol'] = xs
        instance['ysol'] = ys
        instance['inputx'] = widths
        instance['inputy'] = heights

        # generate output string
        out = f"{instance['w']} {instance['h']}\n{instance['n']}\n"
        out += '\n'.join([f"{xi} {yi} {xhati} {yhati}"
                          for xi, yi, xhati, yhati in zip(instance['inputx'], instance['inputy'],
                                                          instance['xsol'], instance['ysol'])])

        # save output string in .txt format at given path:
        project_folder = os.path.abspath(os.path.join(os.getcwd(), "..", ".."))
        file_name = f'out-{index}.txt'
        pathname = os.path.join(project_folder, 'SMT', 'out', 'rotation', 'texts', file_name)
        with open(pathname, 'w') as f:
            f.write(out)

        # save height
        heights_folder = os.path.join(project_folder, 'heights')
        heights, heights_filepath = get_heights(heights_folder, args)
        heights[index] = int(instance['h'])
        with open(heights_filepath, 'w') as f:
            json.dump(heights, f)

        # creating a visualization of the solution and saving it to a file:
        res = [(xi, yi, xhati, yhati)
               for xi, yi, xhati, yhati in
               zip(instance['inputx'], instance['inputy'],
                   instance['xsol'], instance['ysol'])]
        plot_board(instance['w'], instance['h'], res, rot, index)

        return xs, ys, height, time.time() - start_time
    else:
        print("Time limit excedeed\n")
        return [], [], None, 0
