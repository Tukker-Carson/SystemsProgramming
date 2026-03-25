import sys
import random
from collections import deque, defaultdict

PAGE_SIZE = 4096


def parse_trace_line(line):
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    parts = line.split()
    if len(parts) != 2:
        return None
    addr_str, op = parts
    # allow hex or decimal
    addr = int(addr_str, 16)
    return op.upper(), addr


class PageTableEntry:
    def __init__(self, frame=None, dirty=False):
        self.frame = frame
        self.dirty = dirty


class BasePager:
    def __init__(self, num_frames, trace):
        self.num_frames = num_frames
        self.trace = trace

        # page -> PageTableEntry
        self.page_table = {}

        # frame -> page (or None)
        self.frames = [None] * num_frames

        self.disk_reads = 0
        self.disk_writes = 0

    def access(self, page, is_write, t):
        """
        Access a page at time t (for algorithms that need time).
        """
        pte = self.page_table.get(page)

        # Hit
        if pte is not None and pte.frame is not None:
            if is_write:
                pte.dirty = True
            self.on_hit(page, pte.frame, t)
            return

        # Miss: need to bring page in
        self.disk_reads += 1

        # Find free frame if any
        free_frame = None
        for i in range(self.num_frames):
            if self.frames[i] is None:
                free_frame = i
                break

        if free_frame is None:
            # Need to evict
            victim_frame = self.choose_victim_frame(t)
            victim_page = self.frames[victim_frame]
            victim_pte = self.page_table[victim_page]

            if victim_pte.dirty:
                self.disk_writes += 1

            # Evict
            victim_pte.frame = None
            victim_pte.dirty = False

            frame = victim_frame
        else:
            frame = free_frame

        # Load new page
        self.frames[frame] = page
        new_pte = self.page_table.get(page)
        if new_pte is None:
            new_pte = PageTableEntry()
            self.page_table[page] = new_pte
        new_pte.frame = frame
        new_pte.dirty = is_write

        self.on_load(page, frame, t)

    # Hooks for algorithms to override
    def on_hit(self, page, frame, t):
        pass

    def on_load(self, page, frame, t):
        pass

    def choose_victim_frame(self, t):
        raise NotImplementedError

    def run(self):
        for t, (op, addr) in enumerate(self.trace):
            page = addr // PAGE_SIZE
            is_write = (op == 'W')
            self.access(page, is_write, t)
        return self.disk_reads, self.disk_writes


class RandomPager(BasePager):
    def choose_victim_frame(self, t):
        return random.randrange(self.num_frames)


class LRUPager(BasePager):
    def __init__(self, num_frames, trace):
        super().__init__(num_frames, trace)
        # frame -> last access time
        self.last_used = [None] * num_frames

    def on_hit(self, page, frame, t):
        self.last_used[frame] = t

    def on_load(self, page, frame, t):
        self.last_used[frame] = t

    def choose_victim_frame(self, t):
        # choose frame with smallest last_used
        oldest_time = None
        victim = None
        for f in range(self.num_frames):
            if self.last_used[f] is None:
                # shouldn't happen if full, but just in case
                return f
            if oldest_time is None or self.last_used[f] < oldest_time:
                oldest_time = self.last_used[f]
                victim = f
        return victim


class FIFOPager(BasePager):
    def __init__(self, num_frames, trace):
        super().__init__(num_frames, trace)
        # queue of frames in order they were filled
        self.queue = deque()

    def on_load(self, page, frame, t):
        # only enqueue when frame becomes occupied
        if frame not in self.queue:
            self.queue.append(frame)

    def choose_victim_frame(self, t):
        # evict the frame that was loaded longest ago
        if not self.queue:
            # fallback
            return 0
        return self.queue.popleft()


class ClockPager(BasePager):
    def __init__(self, num_frames, trace):
        super().__init__(num_frames, trace)
        self.use_bit = [0] * num_frames
        self.hand = 0

    def on_hit(self, page, frame, t):
        self.use_bit[frame] = 1

    def on_load(self, page, frame, t):
        self.use_bit[frame] = 1

    def choose_victim_frame(self, t):
        while True:
            if self.use_bit[self.hand] == 0:
                victim = self.hand
                self.hand = (self.hand + 1) % self.num_frames
                return victim
            else:
                self.use_bit[self.hand] = 0
                self.hand = (self.hand + 1) % self.num_frames


class IdealPager(BasePager):
    """
    Optimal algorithm: evict the page whose next use is farthest in the future
    (or never used again).
    """
    def __init__(self, num_frames, trace):
        super().__init__(num_frames, trace)
        # Precompute future accesses: for each time and page, know next use
        self.future_uses = self._build_future_uses(trace)

    def _build_future_uses(self, trace):
        # For each page, maintain a list of times it is accessed
        positions = defaultdict(deque)
        for t, (op, addr) in enumerate(trace):
            page = addr // PAGE_SIZE
            positions[page].append(t)

        # For each time, we want to know for each page its next use.
        # But we only need it when choosing a victim: we can query positions on the fly.
        # So we just keep positions and consume from left as we go.
        return positions

    def access(self, page, is_write, t):
        # consume this access from future_uses
        q = self.future_uses[page]
        if q and q[0] == t:
            q.popleft()
        super().access(page, is_write, t)

    def choose_victim_frame(self, t):
        # For each frame, look at the page in it and see its next use time
        farthest_time = -1
        victim = None
        for f in range(self.num_frames):
            page = self.frames[f]
            q = self.future_uses[page]
            if not q:
                # never used again → best victim
                return f
            next_use = q[0]
            if next_use > farthest_time:
                farthest_time = next_use
                victim = f
        return victim


def load_trace(filename):
    trace = []
    with open(filename) as f:
        for line in f:
            parsed = parse_trace_line(line)
            if parsed is not None:
                trace.append(parsed)
    return trace


def run_sim(algorithm, num_frames, trace):
    alg = algorithm.lower()
    if alg == "random":
        pager = RandomPager(num_frames, trace)
    elif alg == "lru":
        pager = LRUPager(num_frames, trace)
    elif alg == "fifo":
        pager = FIFOPager(num_frames, trace)
    elif alg == "clockpage":
        pager = ClockPager(num_frames, trace)
    elif alg == "ideal":
        pager = IdealPager(num_frames, trace)
    else:
        raise ValueError(f"Unknown algorithm: {algorithm}")
    reads, writes = pager.run()
    return reads, writes


def main():
    if len(sys.argv) != 4:
        print("Usage: python vm_sim.py <algorithm> <num_frames> <trace_file>")
        print("Algorithms: random, lru, fifo, clockpage, ideal")
        sys.exit(1)

    algorithm = sys.argv[1]
    num_frames = int(sys.argv[2])
    trace_file = sys.argv[3]

    trace = load_trace(trace_file)
    reads, writes = run_sim(algorithm, num_frames, trace)

    print(f"Algorithm: {algorithm}")
    print(f"Frames: {num_frames}")
    print(f"Disk reads: {reads}")
    print(f"Disk writes: {writes}")


if __name__ == "__main__":
    main()
