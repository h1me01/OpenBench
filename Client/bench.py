# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
#                                                                           #
#   OpenBench is a chess engine testing framework by Andrew Grant.          #
#   <https://github.com/AndyGrant/OpenBench>  <andrew@grantnet.us>          #
#                                                                           #
#   OpenBench is free software: you can redistribute it and/or modify       #
#   it under the terms of the GNU General Public License as published by    #
#   the Free Software Foundation, either version 3 of the License, or       #
#   (at your option) any later version.                                     #
#                                                                           #
#   OpenBench is distributed in the hope that it will be useful,            #
#   but WITHOUT ANY WARRANTY; without even the implied warranty of          #
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the           #
#   GNU General Public License for more details.                            #
#                                                                           #
#   You should have received a copy of the GNU General Public License       #
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.   #
#                                                                           #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

# The sole purpose of this module is to invoke run_benchmark().
#
#   - binary   : Path to, and including, the Binary File
#   - network  : Path to Network File, or None
#   - private  : True or False; Private NNUE engines require special care
#   - threads  : Number of concurrent benches to run
#   - sets     : Number of times to repeat this experiment
#   - expected : None, or an expected value, which if not matched raises Exceptions
#
# run_benchmark() may raise utils.OpenBenchBadBenchException.
# An associated error message, including the binary name, is included

import multiprocessing
import os
import queue
import re
import subprocess
import sys

from utils import kill_process_by_name
from utils import OpenBenchBadBenchException

MAX_BENCH_TIME_SECONDS = 60

def parse_stream_output(stream):
    nps = bench = None  # Initialize values

    # Split lines and reverse for processing
    lines = stream.decode('ascii').strip().split('\n')[::-1]

    for line in lines:
        # Convert non alpha-numerics to spaces
        line = re.sub(r'[^a-zA-Z0-9 ]+', ' ', line)

        # Define patterns for NPS and Bench results
        nps_pattern = r'(\d+\s+nps)|(nps\s+\d+)'
        bench_pattern = r'(\d+\s+nodes)|(nodes\s+\d+)'

        # Match NPS
        re_nps = re.search(nps_pattern, line, re.IGNORECASE)
        if re_nps:
            nps = int(re.search(r'\d+', re_nps.group()).group())

        # Match Bench
        re_bench = re.search(bench_pattern, line, re.IGNORECASE)
        if re_bench:
            bench = int(re.search(r'\d+', re_bench.group()).group())

        # Check if this line contains the total nodes and NPS
        if 'nodes' in line and 'nps' in line:
            parts = line.split()
            try:
                bench = int(parts[0])  # Assuming the first part is the node count
                nps = int(parts[2])    # Assuming the second part is the NPS
            except (ValueError, IndexError):
                print("Failed to parse nodes or nps from:", line)
                
    return (bench, nps)

def single_core_bench(binary, network, private, outqueue):

    # Basic command for Public engines
    cmd = ['./%s' % (binary), 'bench']

    # Adjust to handle setting Networks in Private engines
    if network and private:
        option = 'setoption name EvalFile value %s' % (network)
        cmd = ['./%s' % (binary), option, 'bench', 'quit']

    try: # Launch the bench and wait for results
        stdout, stderr = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        ).communicate()
        outqueue.put(parse_stream_output(stdout))

    except: # Signal an error with (None, None)
        outqueue.put(("None", None))

def multi_core_bench(binary, network, private, threads):

    outqueue = multiprocessing.Queue()

    processes = [
        multiprocessing.Process(
            target=single_core_bench, args=(binary, network, private, outqueue))
        for ii in range(threads)
    ]

    for process in processes:
        process.start()

    try: # Every process deposits exactly one result into the Queue
        return [outqueue.get(timeout=MAX_BENCH_TIME_SECONDS) for ii in range(threads)]

    except queue.Empty: # Force kill the engine, thus causing the processes to finish
        kill_process_by_name(binary)
        raise OpenBenchBadBenchException('[%s] Bench Exceeded Max Duration' % (binary))

    finally: # Join everything to avoid zombie processes
        for process in processes:
            process.join()

def run_benchmark(binary, network, private, threads, sets, expected=None):

    engine = os.path.basename(binary)

    benches, speeds = [], []
    for ii in range(sets):
        for bench, speed in multi_core_bench(binary, network, private, threads):
            benches.append(bench); speeds.append(speed)

    if len(set(benches)) != 1:
        raise OpenBenchBadBenchException('[%s] Non-Deterministic Benches' % (engine))

    if None in benches or None in speeds:
        raise OpenBenchBadBenchException('[%s] Failed to Execute Benchmark' % (engine))

    if expected and expected != benches[0]:
        raise OpenBenchBadBenchException('[%s] Wrong Bench: %d' % (engine, benches[0]))

    return int(sum(speeds) / len(speeds)), benches[0]
