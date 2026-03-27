# Made by Grant R and Carson T (Grarson)
import sys
import random
from collections import deque

PAGE_SIZE = 4096

# Page Table Entry object to make it easy to store a frame and the dirty bit
class PageTableEntry:
    def __init__(self, frame=None, dirty=False, counter=0):
        self.frame = frame
        self.dirty = dirty
        self.accessTime = counter
        self.hasLife = True

# Abstract Pager (except I don't like python object oriented programming so it's not actually abstract)
class Pager:
    def __init__(self, nframes, trace, debug):
        self.nframes = nframes
        self.trace = trace
        self.debug = debug
        self.page_table = {}
        self.frames = [None]*nframes
        self.nreads = 0
        self.nwrites = 0
        self.counter = 0

    def access(self, page, write):
        # Access a given page
        self.counter += 1
        entry = self.page_table.get(page)

        # Hit
        if entry is not None and entry.frame is not None:
            if write:
                entry.dirty = True
            if self.debug:
                print(f"Hit Page, Frame - {page}, {entry.frame}")
            self.on_hit(page, entry)
            return
        
        # Miss - Load New Page
        self.nreads += 1
        new_frame = None
        for i in range(self.nframes):
            if self.frames[i] is None:
                new_frame = i
                break

        if new_frame is None:
            # Remove Frame
            new_frame = self.drop_frame()
            old_entry = self.page_table[self.frames[new_frame]]
            if self.debug:
                print(f"Dropping Page, Frame - {page}, {old_entry.frame}")
            if old_entry.dirty:
                self.nwrites += 1
            old_entry.frame = None
            old_entry.dirty = False

        self.frames[new_frame] = page
        new_entry = PageTableEntry(counter=self.counter)
        self.page_table[page] = new_entry

        if self.debug:
                print(f"Adding Page, Entry - {page}, {new_entry}")
        new_entry.frame = new_frame
        new_entry.dirty = write

        self.on_load(page, new_entry)

    def run(self):
        for addr, op in self.trace:
            page = addr // PAGE_SIZE
            if self.debug:
                print(f"Accessing Address {addr} (Page {page}) - {'Write' if op else 'Read'}")
            self.access(page, op)
        return self.nreads, self.nwrites

    # Overrides
    def on_hit(self, page, entry):
        pass

    def on_load(self, page, entry):
        pass

    def drop_frame(self):
        raise NotImplementedError


# Random Pager
class RandomPager(Pager):
    def drop_frame(self):
        return random.randrange(self.nframes)
    
# FIFO Pager
class FIFOPager(Pager):
    # First in First Out = Queue!
    def __init__(self, nframes, trace, debug):
        super().__init__(nframes, trace, debug)
        self.queue = deque()

    def on_load(self, page, entry):
        if entry.frame not in self.queue:
            self.queue.append(entry.frame)

    def drop_frame(self):
        return self.queue.popleft()
        
class LRUPager(Pager):
    def on_hit(self, page, entry):
        entry.accessTime = self.counter
    
    def drop_frame(self):
        lruFrame = (0,None)
        for i,frame in enumerate(self.frames):
            value = self.page_table[frame].accessTime
            if lruFrame[1] is None or value <= lruFrame[1]:
                lruFrame = (i,value)
        return lruFrame[0]

class ClockPager(Pager):
    def __init__(self, nframes, trace, debug):
        super().__init__(nframes, trace, debug)
        self.queue = deque()
    
    def on_load(self, page, entry):
        if entry.frame not in self.queue:
            self.queue.append(entry.frame)
    
    def on_hit(self, page, entry):
        entry.hasLife = True

    def drop_frame(self):
        while True:
            leftFrame = self.queue.popleft()
            if self.page_table[self.frames[leftFrame]].hasLife is False:
                return leftFrame
            else:
                self.page_table[self.frames[leftFrame]].hasLife = False
                self.queue.append(leftFrame)

class IdealPager(Pager):
    def futureSight(self, page):
        for i,address in enumerate(trace[self.counter+1:]):
            address = address[0] // PAGE_SIZE
            if address == page:
                return i + self.counter + 1
        return None

    def on_hit(self, page, entry):
        entry.accessTime = self.futureSight(page)
    
    def on_load(self, page, entry):
        entry.accessTime = self.futureSight(page)
        
    def drop_frame(self):
        lruFrame = (0,None)
        for i,frame in enumerate(self.frames):
            value = self.page_table[frame].accessTime
            if value is None:
                return i
            if lruFrame[1] is None or value >= lruFrame[1]:
                lruFrame = (i,value)
        return lruFrame[0]


if __name__ == "__main__":
    # Get Arguments
    if len(sys.argv) != 5:
        print("python PageTable.py <nframes> <random|lru|fifo|clockpage|ideal> <quiet|debug> <tracefile>")
        sys.exit(1)
    
    nframes = int(sys.argv[1])
    algorithm = sys.argv[2].lower()
    debug = sys.argv[3].lower()=="debug"
    tracefile = sys.argv[4]

    # Load Trace File
    trace = []
    with open(tracefile) as f:
        for line in f:
            addr, op = line.strip().split()
            trace.append((int(addr, 16), op=="W"))
    
    # Run Simulation
    alg = algorithm.lower()
    if alg == "random":
        pager = RandomPager(nframes, trace, debug)
    elif alg == "lru":
        pager = LRUPager(nframes, trace, debug)
    elif alg == "fifo":
        pager = FIFOPager(nframes, trace, debug)
    elif alg == "clockpage":
        pager = ClockPager(nframes, trace, debug)
    elif alg == "ideal":
        pager = IdealPager(nframes, trace, debug)
    else:
        raise ValueError(f"Unknown algorithm: {algorithm}")
    nreads, nwrites = pager.run()

    # Print Results
    print(f"Algorithm: {algorithm}")
    print(f"Frames: {nframes}")
    print(f"Disk reads: {nreads}")
    print(f"Disk writes: {nwrites}")