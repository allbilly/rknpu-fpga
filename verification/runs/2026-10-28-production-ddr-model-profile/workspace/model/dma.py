"""Raw command-memory PC replay oracle, never a hardware execution fallback."""
from .profile import Decoder, ProfileError, decode
from .sim import RKEmulator

TAIL_KEYS = ((0x0101, 0x10), (0x0101, 0x14), (0x0041, 0), (0x0081, 8))


class DMAEmulator(RKEmulator):
    def __init__(self, memory, max_tasks=4095):
        super().__init__(memory)
        if not 1 <= max_tasks <= 4095:
            raise ValueError('max_tasks must be 1..4095')
        self.decoder = Decoder(pc_dma=True)
        self.max_tasks = max_tasks
        self.command_reads = 0
        self.jobs = 0

    def submit(self, raw_regcmd):
        raise TypeError('DMA replay requires command-memory address and descriptor amount')

    def submit_dma(self, address, amount):
        if self.fault:
            raise self.fault
        start_completed = self.completed
        try:
            while True:
                if not 0 <= address < 1 << 32 or address % 16 or not 4 <= amount <= 65539 or address+8*amount > 1 << 32:
                    raise ProfileError(7, 'command address/count/range')
                cfg = None
                for index in range(amount):
                    word = 0
                    for part in range(4):
                        self.command_reads += 1
                        word |= self.memory.read16(address+index*8+part*2) << (part*16)
                    key = decode(word)[:2]
                    remaining = amount-index
                    if (remaining <= 4 and key != TAIL_KEYS[4-remaining]) or (remaining > 4 and key in TAIL_KEYS):
                        raise ProfileError(3, 'misplaced PC tail/enable')
                    cfg = self.decoder.feed(word)
                if cfg is None:
                    raise ProfileError(3, 'missing task trigger')
                self.execute(cfg)
                if not cfg.next_amount:
                    self.jobs += 1
                    return
                if self.completed-start_completed >= self.max_tasks:
                    raise ProfileError(7, 'task limit reached')
                address, amount = cfg.next_address, cfg.next_amount+4
        except ProfileError as error:
            self.fault = error
            raise
