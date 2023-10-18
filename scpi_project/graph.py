#! /usr/bin/env python3
"""Graphing module"""

from argparse import ArgumentParser

import matplotlib.pyplot as plt


def load_file(filename):
    """Load data from file"""
    data = []
    with open(file=filename, mode='r', encoding='utf-8') as file:
        for line in file:
            data.append(float(line.strip()))
    return data


def plot_chart(data):
    """Plot chart"""
    # fig = plt.figure()
    ax = plt.axes()
    ax.plot(range(len(data)), data)
    plt.show()


def handle_graph(args):
    """Handle graph command"""
    data = load_file(args.filename)
    print(f"Average: {sum(data)/len(data)}")
    print(f"Max: {max(data)}")
    plot_chart(data)


def handle_stats(args):
    """Handle stats command"""
    data = load_file(args.filename)
    start = int(args.start)
    end = int(args.end)
    if end == 0:
        end = len(data)

    print(f"Start:   {start}")
    print(f"End:     {end}")
    print(f"Length:  {end-start}")
    print(f"Average: {sum(data[start:end])/len(data[start:end])}")
    print(f"Max:     {max(data[start:end])}")


def main():
    """Entry Point"""
    parser = ArgumentParser()

    parser.add_argument("-f", "--filename", required=True, help="Filename with data to graph.  Rows of numbers.")

    subparsers = parser.add_subparsers(help="Subcommands:")

    graph_parser = subparsers.add_parser("graph", help="Load data from file and create a graph")
    graph_parser.set_defaults(func=handle_graph)

    stats_parser = subparsers.add_parser("stats", help="Load data from file and calculate stats")
    stats_parser.add_argument(
        "-s", "--start",
        default=0,
        help="Calc stats from window start from this sample number.  Default is 0."
    )
    stats_parser.add_argument(
        "-e", "--end",
        default=0,
        help="Calc stats to window end at this sample number.  Default is end of data."
    )
    stats_parser.set_defaults(func=handle_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
