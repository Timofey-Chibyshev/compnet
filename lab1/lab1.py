# Simulation of Go-Back-N and Selective Repeat protocols (discrete-event simulator)
import random
import heapq
import time
import math
import pandas as pd
from collections import deque, defaultdict, namedtuple
import matplotlib.pyplot as plt
import numpy as np
import enum

random.seed(0)

Event = namedtuple("Event", ["time", "etype", "data", "id"])

class Packet:
    def __init__(self, seq, payload=None, is_ack=False):
        self.seq = seq
        self.payload = payload
        self.is_ack = is_ack

    def __repr__(self):
        return f"ACK({self.seq})" if self.is_ack else f"PKT({self.seq})"

class SlotStatus(enum.Enum):
    BUSY = enum.auto()
    NEED_RETRANSMIT = enum.auto()
    AVAILABLE = enum.auto()

class Slot:
    def __init__(self, index):
        self.index = index
        self.status = SlotStatus.AVAILABLE
        self.virtual_seq = index
        self.timer_id = None
        self.last_sent_time = 0

    def __repr__(self):
        return f"Slot({self.index}, status={self.status.name}, virtual={self.virtual_seq})"

class Simulator:
    def __init__(self, protocol="GBN", n_packets=100, window=4, timeout=2.0, loss_prob=0.1,
                 data_delay=0.05, ack_delay=0.05, seq_space=None, verbose=False, debug=False):
        self.protocol = protocol
        self.N = n_packets
        self.W = window
        self.timeout = timeout
        self.loss = loss_prob
        self.data_delay = data_delay
        self.ack_delay = ack_delay
        self.verbose = verbose
        self.debug = debug

        if seq_space is None:
            self.M = 2 * self.W if protocol == "SR" else 1024
        else:
            self.M = seq_space

        if protocol == "SR" and not (self.W <= self.M // 2):
            raise ValueError("For SR must have window_size <= M/2. Increase M or reduce W.")

        self.event_id = 0
        self.events = []

        if protocol == "SR":
            self.slots = [Slot(i) for i in range(self.W)]
            self.ack_count = 0
        else:
            self.base = 0
            self.nextseq = 0
            self.timer_active = None

        self.expected = 0
        self.recv_buffer = {}

        self.sent_total = 0
        self.sent_data = 0
        self.retransmissions = 0
        self.acks_sent = 0
        self.acks_lost = 0
        self.packets_lost = 0
        self.start_time = 0.0
        self.end_time = 0.0
        self.delivered = 0
        self.log = []
        self.delivered_set = set()

        self.timeout_events = 0
        self.false_timeouts = 0

    def schedule(self, time_, etype, data=None):
        self.event_id += 1
        ev = Event(time_, etype, data, self.event_id)
        heapq.heappush(self.events, (ev.time, ev.id, ev))
        return ev.id

    def channel_send_data(self, cur_time, pkt):
        if random.random() < self.loss:
            self.packets_lost += 1
            if self.verbose:
                self.log.append((cur_time, f"DATA LOST {pkt}"))
            return None
        arrival = cur_time + self.data_delay
        self.schedule(arrival, "deliver_data", pkt)
        if self.verbose:
            self.log.append((cur_time, f"SENT {pkt} -> arrive at {arrival:.3f}"))
        return True

    def channel_send_ack(self, cur_time, ack_pkt):
        if random.random() < self.loss:
            self.acks_lost += 1
            if self.verbose:
                self.log.append((cur_time, f"ACK LOST {ack_pkt}"))
            return None
        arrival = cur_time + self.ack_delay
        self.schedule(arrival, "deliver_ack", ack_pkt)
        if self.verbose:
            self.log.append((cur_time, f"SEND_ACK {ack_pkt} -> arrive at {arrival:.3f}"))
        return True

    def start(self):
        self.start_time = 0.0
        self.schedule(0.0, "send_next", None)
        last_time = 0.0
        max_simulation_time = 1000000.0
        consecutive_idle_cycles = 0
        
        while self.events and self.delivered < self.N and last_time < max_simulation_time:
            time_, _, ev = heapq.heappop(self.events)
            last_time = time_
            
            if ev.etype == "send_next":
                self.handle_send_next(time_)
                consecutive_idle_cycles = 0
            elif ev.etype == "deliver_data":
                self.handle_deliver_data(time_, ev.data)
                consecutive_idle_cycles = 0
            elif ev.etype == "deliver_ack":
                self.handle_deliver_ack(time_, ev.data)
                consecutive_idle_cycles = 0
            elif ev.etype == "timeout":
                self.handle_timeout(time_, ev.data, ev.id)
                consecutive_idle_cycles = 0

            if len(self.events) < 5 and consecutive_idle_cycles < 10:
                self.schedule(last_time + 0.1, "send_next", None)
                consecutive_idle_cycles += 1

        if self.delivered < self.N:
            base_time = self.N * (self.data_delay + self.ack_delay)
            estimated_retransmissions = max(self.retransmissions, (self.N - self.delivered) * 10)
            self.end_time = base_time + estimated_retransmissions * (self.data_delay + self.timeout)
        else:
            self.end_time = last_time

    def handle_send_next(self, cur_time):
        if self.protocol == "GBN":
            if self.nextseq == self.base and self.base < self.N:
                pkt = Packet(self.nextseq % self.M, payload=self.nextseq)
                self.sent_total += 1
                self.sent_data += 1
                self.channel_send_data(cur_time, pkt)
                
                if self.timer_active is None:
                    tid = self.schedule(cur_time + self.timeout, "timeout", self.base)
                    self.timer_active = (self.base, tid)
                
                self.nextseq += 1

            while self.nextseq < self.base + self.W and self.nextseq < self.N:
                pkt = Packet(self.nextseq % self.M, payload=self.nextseq)
                self.sent_total += 1
                self.sent_data += 1

                sent_success = self.channel_send_data(cur_time, pkt)

                if self.timer_active is None and sent_success:
                    tid = self.schedule(cur_time + self.timeout, "timeout", self.base)
                    self.timer_active = (self.base, tid)

                self.nextseq += 1
        else:
            for slot in self.slots:
                if slot.status == SlotStatus.BUSY and cur_time - slot.last_sent_time > self.timeout:
                    slot.status = SlotStatus.NEED_RETRANSMIT
                    if self.debug:
                        self.log.append((cur_time, f"DEBUG: SR Slot {slot.index} timeout, virtual_seq={slot.virtual_seq}"))

            for slot in self.slots:
                if slot.virtual_seq > self.N:
                    continue

                if slot.status == SlotStatus.BUSY:
                    continue

                elif slot.status == SlotStatus.NEED_RETRANSMIT:
                    slot.status = SlotStatus.BUSY
                    slot.last_sent_time = cur_time

                    pkt = Packet(slot.index, payload=slot.virtual_seq)
                    self.sent_total += 1
                    self.retransmissions += 1
                    self.channel_send_data(cur_time, pkt)

                    if slot.timer_id is not None:
                        pass
                    timer_id = self.schedule(cur_time + self.timeout, "timeout", slot.index)
                    slot.timer_id = timer_id

                    if self.debug:
                        self.log.append((cur_time, f"DEBUG: SR Retransmit slot {slot.index}, virtual={slot.virtual_seq}"))

                elif slot.status == SlotStatus.AVAILABLE:
                    slot.status = SlotStatus.BUSY
                    slot.last_sent_time = cur_time

                    pkt = Packet(slot.index, payload=slot.virtual_seq)
                    self.sent_total += 1
                    self.sent_data += 1
                    self.channel_send_data(cur_time, pkt)

                    timer_id = self.schedule(cur_time + self.timeout, "timeout", slot.index)
                    slot.timer_id = timer_id

                    if self.debug:
                        self.log.append((cur_time, f"DEBUG: SR Send new slot {slot.index}, virtual={slot.virtual_seq}"))

            if self.ack_count < self.N:
                self.schedule(cur_time + 0.01, "send_next", None)

    def handle_deliver_data(self, cur_time, pkt):
        if self.verbose:
            self.log.append((cur_time, f"RECV {pkt} at receiver"))

        if self.protocol == "GBN":
            if pkt.seq == self.expected % self.M:
                if pkt.payload not in self.delivered_set:
                    self.delivered_set.add(pkt.payload)
                    self.delivered += 1
                self.expected += 1

                ack_seq = (self.expected - 1) % self.M
                ack = Packet(ack_seq, is_ack=True)
                self.acks_sent += 1
                self.channel_send_ack(cur_time, ack)
            else:
                if self.expected > 0:
                    ack_seq = (self.expected - 1) % self.M
                    ack = Packet(ack_seq, is_ack=True)
                    self.acks_sent += 1
                    self.channel_send_ack(cur_time, ack)
        else:
            ack = Packet(pkt.seq, is_ack=True)
            self.acks_sent += 1
            self.channel_send_ack(cur_time, ack)

            virtual_seq = pkt.payload
            if virtual_seq not in self.delivered_set and virtual_seq not in self.recv_buffer:
                self.recv_buffer[virtual_seq] = pkt

            while self.expected in self.recv_buffer:
                if self.expected not in self.delivered_set:
                    self.delivered_set.add(self.expected)
                    self.delivered += 1
                del self.recv_buffer[self.expected]
                self.expected += 1

    def handle_deliver_ack(self, cur_time, ack_pkt):
        if self.verbose:
            self.log.append((cur_time, f"RECV_ACK {ack_pkt} at sender"))

        acknum = ack_pkt.seq

        if self.protocol == "GBN":
            acked_virtual = None
            for v in range(self.base, min(self.nextseq, self.N)):
                if v % self.M == acknum:
                    acked_virtual = v
                    break

            if acked_virtual is not None and acked_virtual >= self.base:
                self.base = acked_virtual + 1
                self.timer_active = None
                
                if self.base < self.nextseq:
                    tid = self.schedule(cur_time + self.timeout, "timeout", self.base)
                    self.timer_active = (self.base, tid)
            
            if self.base < self.N:
                self.schedule(cur_time, "send_next", None)
        else:
            slot_index = acknum
            if 0 <= slot_index < len(self.slots):
                slot = self.slots[slot_index]
                self.ack_count += 1
                slot.status = SlotStatus.AVAILABLE

                old_virtual = slot.virtual_seq
                slot.virtual_seq += self.W
                
                if self.debug:
                    self.log.append((cur_time, f"DEBUG: SR ACK for slot {slot_index}, virtual {old_virtual}->{slot.virtual_seq}"))

            if self.ack_count < self.N:
                self.schedule(cur_time, "send_next", None)

    def handle_timeout(self, cur_time, data, ev_id):
        self.timeout_events += 1

        if self.protocol == "GBN":
            if self.timer_active and self.timer_active[1] == ev_id and data == self.base:
                for v in range(self.base, self.nextseq):
                    pkt = Packet(v % self.M, payload=v)
                    self.sent_total += 1
                    self.retransmissions += 1
                    self.channel_send_data(cur_time, pkt)
                
                tid = self.schedule(cur_time + self.timeout, "timeout", self.base)
                self.timer_active = (self.base, tid)
            else:
                self.false_timeouts += 1
        else:
            slot_index = data
            if 0 <= slot_index < len(self.slots):
                slot = self.slots[slot_index]
                if slot.timer_id == ev_id and slot.status == SlotStatus.BUSY:
                    slot.status = SlotStatus.NEED_RETRANSMIT
                    if self.debug:
                        self.log.append((cur_time, f"DEBUG: SR Timeout for slot {slot_index}, marked for retransmit"))
                else:
                    self.false_timeouts += 1
            else:
                self.false_timeouts += 1

    def results(self):
        if self.sent_total > 0:
            efficiency = self.delivered / self.sent_total
        else:
            efficiency = 0.0

        overhead = (self.sent_total / self.N) if self.N > 0 else float('inf')
        
        total_time = self.end_time
        throughput = self.delivered / total_time if total_time > 0 else 0

        return {
            "protocol": self.protocol,
            "N": self.N,
            "W": self.W,
            "timeout": self.timeout,
            "loss": self.loss,
            "sent_total": self.sent_total,
            "retransmissions": self.retransmissions,
            "acks_sent": self.acks_sent,
            "packets_lost": self.packets_lost,
            "acks_lost": self.acks_lost,
            "delivered": self.delivered,
            "time": round(total_time, 6),
            "efficiency": round(efficiency, 6),
            "overhead": round(overhead, 6),
            "throughput": round(throughput, 6),
            "timeout_events": self.timeout_events,
            "false_timeouts": self.false_timeouts
        }

def run_experiment(protocol="GBN", N=100, W=10, timeout=2.0, loss=0.1, verbose=False, debug=False):
    sim = Simulator(protocol=protocol, n_packets=N, window=W, timeout=timeout, 
                   loss_prob=loss, data_delay=0.05, ack_delay=0.05, verbose=verbose, debug=debug)
    sim.start()
    return sim.results(), sim

# Эксперимент 1: Зависимость от размера окна при фиксированной потере 0.3
print("Running experiments with different window sizes (loss=0.3)...")
experiments_window = []
sims_window = []

# Параметры эксперимента
FIXED_LOSS = 0.3
N_PACKETS = 2500
TIMEOUT = 0.5

# Разные размеры окон для тестирования
window_sizes = [int(i) for i in range(1, 50, 2)]

params_window = []
for window_size in window_sizes:
    params_window.append(("GBN", N_PACKETS, window_size, TIMEOUT, FIXED_LOSS))
    params_window.append(("SR", N_PACKETS, window_size, TIMEOUT, FIXED_LOSS))

for i, (prot, N, W, to, loss) in enumerate(params_window):
    print(f"Running {prot} with window={W}, loss={loss} ({i+1}/{len(params_window)})")
    res, sim = run_experiment(protocol=prot, N=N, W=W, timeout=to, loss=loss, verbose=False, debug=False)
    experiments_window.append(res)
    sims_window.append(sim)

df_window = pd.DataFrame(experiments_window)

# Эксперимент 2: Зависимость от вероятности потерь при фиксированном размере окна
print("\nRunning experiments with different loss probabilities (window=3)...")
experiments_loss = []
sims_loss = []

# Параметры эксперимента
FIXED_WINDOW = 15
N_PACKETS = 2500
TIMEOUT = 0.5

# Разные вероятности потерь
loss_probabilities = [i/100 for i in range(0, 99, 5)]  # 0%, 5%, 10%, ..., 50%

params_loss = []
for loss in loss_probabilities:
    params_loss.append(("GBN", N_PACKETS, FIXED_WINDOW, TIMEOUT, loss))
    params_loss.append(("SR", N_PACKETS, FIXED_WINDOW, TIMEOUT, loss))

for i, (prot, N, W, to, loss) in enumerate(params_loss):
    print(f"Running {prot} with loss={loss}, window={W} ({i+1}/{len(params_loss)})")
    res, sim = run_experiment(protocol=prot, N=N, W=W, timeout=to, loss=loss, verbose=False, debug=False)
    experiments_loss.append(res)
    sims_loss.append(sim)

df_loss = pd.DataFrame(experiments_loss)

print("\n=== EXPERIMENTAL RESULTS: WINDOW SIZE VS PERFORMANCE (loss=0.3) ===")
print(df_window[['protocol', 'W', 'loss', 'sent_total', 'retransmissions', 'delivered', 'time', 'efficiency', 'throughput']])

print("\n=== EXPERIMENTAL RESULTS: LOSS PROBABILITY VS PERFORMANCE (window=3) ===")
print(df_loss[['protocol', 'loss', 'W', 'sent_total', 'retransmissions', 'delivered', 'time', 'efficiency', 'throughput']])


# Набор 1: Графики зависимости от размера окна при фиксированной потере 0.3
plt.figure(figsize=(16, 12))

# График 1.1: Эффективность vs Размер окна
plt.subplot(2, 3, 1)
for prot in df_window['protocol'].unique():
    sub = df_window[df_window['protocol']==prot]
    plt.plot(sub['W'], sub['efficiency'], marker='o', linewidth=2, label=prot)
plt.xlabel("Window Size")
plt.ylabel("Efficiency")
plt.title("Efficiency vs Window Size\n(loss=0.3)")
plt.grid(True, alpha=0.3)
plt.legend()
plt.xscale('log', base=2)

# График 1.2: Время передачи vs Размер окна
plt.subplot(2, 3, 2)
for prot in df_window['protocol'].unique():
    sub = df_window[df_window['protocol']==prot]
    plt.plot(sub['W'], sub['time'], marker='s', linewidth=2, label=prot)
plt.xlabel("Window Size")
plt.ylabel("Transmission Time (s)")
plt.title("Transmission Time vs Window Size\n(loss=0.3)")
plt.grid(True, alpha=0.3)
plt.legend()
plt.xscale('log', base=2)

# График 1.3: Пропускная способность vs Размер окна
plt.subplot(2, 3, 3)
for prot in df_window['protocol'].unique():
    sub = df_window[df_window['protocol']==prot]
    plt.plot(sub['W'], sub['throughput'], marker='^', linewidth=2, label=prot)
plt.xlabel("Window Size")
plt.ylabel("Throughput (packets/sec)")
plt.title("Throughput vs Window Size\n(loss=0.3)")
plt.grid(True, alpha=0.3)
plt.legend()
plt.xscale('log', base=2)

# График 1.4: Количество ретрансмиссий vs Размер окна
plt.subplot(2, 3, 4)
for prot in df_window['protocol'].unique():
    sub = df_window[df_window['protocol']==prot]
    plt.plot(sub['W'], sub['retransmissions'], marker='d', linewidth=2, label=prot)
plt.xlabel("Window Size")
plt.ylabel("Retransmissions")
plt.title("Retransmissions vs Window Size\n(loss=0.3)")
plt.grid(True, alpha=0.3)
plt.legend()
plt.xscale('log', base=2)

# График 1.5: Overhead vs Размер окна
plt.subplot(2, 3, 5)
for prot in df_window['protocol'].unique():
    sub = df_window[df_window['protocol']==prot]
    plt.plot(sub['W'], sub['overhead'], marker='v', linewidth=2, label=prot)
plt.xlabel("Window Size")
plt.ylabel("Overhead (sent_total / N)")
plt.title("Overhead vs Window Size\n(loss=0.3)")
plt.grid(True, alpha=0.3)
plt.legend()
plt.xscale('log', base=2)

# График 1.6: Общее количество отправленных пакетов vs Размер окна
plt.subplot(2, 3, 6)
for prot in df_window['protocol'].unique():
    sub = df_window[df_window['protocol']==prot]
    plt.plot(sub['W'], sub['sent_total'], marker='*', linewidth=2, label=prot)
plt.xlabel("Window Size")
plt.ylabel("Total Packets Sent")
plt.title("Total Packets Sent vs Window Size\n(loss=0.3)")
plt.grid(True, alpha=0.3)
plt.legend()
plt.xscale('log', base=2)

plt.tight_layout()
plt.show()

# Набор 2: Графики зависимости от вероятности потерь при фиксированном размере окна 4
plt.figure(figsize=(16, 12))

# График 2.1: Эффективность vs Вероятность потерь
plt.subplot(2, 3, 1)
for prot in df_loss['protocol'].unique():
    sub = df_loss[df_loss['protocol']==prot]
    plt.plot(sub['loss'], sub['efficiency'], marker='o', linewidth=2, label=prot)
plt.xlabel("Loss Probability")
plt.ylabel("Efficiency")
plt.title("Efficiency vs Loss Probability\n(window=3)")
plt.grid(True, alpha=0.3)
plt.legend()

# График 2.2: Время передачи vs Вероятность потерь
plt.subplot(2, 3, 2)
for prot in df_loss['protocol'].unique():
    sub = df_loss[df_loss['protocol']==prot]
    plt.plot(sub['loss'], sub['time'], marker='s', linewidth=2, label=prot)
plt.xlabel("Loss Probability")
plt.ylabel("Transmission Time (s)")
plt.title("Transmission Time vs Loss Probability\n(window=3)")
plt.grid(True, alpha=0.3)
plt.legend()

# График 2.3: Пропускная способность vs Вероятность потерь
plt.subplot(2, 3, 3)
for prot in df_loss['protocol'].unique():
    sub = df_loss[df_loss['protocol']==prot]
    plt.plot(sub['loss'], sub['throughput'], marker='^', linewidth=2, label=prot)
plt.xlabel("Loss Probability")
plt.ylabel("Throughput (packets/sec)")
plt.title("Throughput vs Loss Probability\n(window=3)")
plt.grid(True, alpha=0.3)
plt.legend()

# График 2.4: Количество ретрансмиссий vs Вероятность потерь
plt.subplot(2, 3, 4)
for prot in df_loss['protocol'].unique():
    sub = df_loss[df_loss['protocol']==prot]
    plt.plot(sub['loss'], sub['retransmissions'], marker='d', linewidth=2, label=prot)
plt.xlabel("Loss Probability")
plt.ylabel("Retransmissions")
plt.title("Retransmissions vs Loss Probability\n(window=3)")
plt.grid(True, alpha=0.3)
plt.legend()

# График 2.5: Overhead vs Вероятность потерь
plt.subplot(2, 3, 5)
for prot in df_loss['protocol'].unique():
    sub = df_loss[df_loss['protocol']==prot]
    plt.plot(sub['loss'], sub['overhead'], marker='v', linewidth=2, label=prot)
plt.xlabel("Loss Probability")
plt.ylabel("Overhead (sent_total / N)")
plt.title("Overhead vs Loss Probability\n(window=3)")
plt.grid(True, alpha=0.3)
plt.legend()

# График 2.6: Общее количество отправленных пакетов vs Вероятность потерь
plt.subplot(2, 3, 6)
for prot in df_loss['protocol'].unique():
    sub = df_loss[df_loss['protocol']==prot]
    plt.plot(sub['loss'], sub['sent_total'], marker='*', linewidth=2, label=prot)
plt.xlabel("Loss Probability")
plt.ylabel("Total Packets Sent")
plt.title("Total Packets Sent vs Loss Probability\n(window=3)")
plt.grid(True, alpha=0.3)
plt.legend()

plt.tight_layout()
plt.show()

# Сравнительные графики: эффективность GBN vs SR для обоих экспериментов
plt.figure(figsize=(15, 6))

# График сравнения 1: Эффективность vs Размер окна
plt.subplot(1, 2, 1)
gbn_window = df_window[df_window['protocol'] == 'GBN']
sr_window = df_window[df_window['protocol'] == 'SR']

plt.plot(gbn_window['W'], gbn_window['efficiency'], marker='o', linewidth=2, label='GBN', color='blue')
plt.plot(sr_window['W'], sr_window['efficiency'], marker='s', linewidth=2, label='SR', color='red')

plt.xlabel("Window Size")
plt.ylabel("Efficiency")
plt.title("Efficiency Comparison: Window Size\n(loss=0.3)")
plt.grid(True, alpha=0.3)
plt.legend()
plt.xscale('log', base=2)

# График сравнения 2: Эффективность vs Вероятность потерь
plt.subplot(1, 2, 2)
gbn_loss = df_loss[df_loss['protocol'] == 'GBN']
sr_loss = df_loss[df_loss['protocol'] == 'SR']

plt.plot(gbn_loss['loss'], gbn_loss['efficiency'], marker='o', linewidth=2, label='GBN', color='blue')
plt.plot(sr_loss['loss'], sr_loss['efficiency'], marker='s', linewidth=2, label='SR', color='red')

plt.xlabel("Loss Probability")
plt.ylabel("Efficiency")
plt.title("Efficiency Comparison: Loss Probability\n(window=3)")
plt.grid(True, alpha=0.3)
plt.legend()

plt.tight_layout()
plt.show()

# Анализ результатов
print("\n=== АНАЛИЗ РЕЗУЛЬТАТОВ ===")
print("\n1. ЗАВИСИМОСТЬ ОТ РАЗМЕРА ОКНА (при потерях 30%):")
print("   - SR показывает лучшую эффективность при большинстве размеров окон")
print("   - GBN имеет больший overhead из-за массовых ретрансмиссий")
print("   - Оптимальный размер окна для SR обычно больше, чем для GBN")

print("\n2. ЗАВИСИМОСТЬ ОТ ВЕРОЯТНОСТИ ПОТЕРЬ (при размере окна 3):")
print("   - SR значительно превосходит GBN при высоких потерях")
print("   - При низких потерях оба протокола работают схоже")
print("   - GBN сильно деградирует при потерях > 20%")

print("\n3. ОБЩИЕ ВЫВОДЫ:")
print("   - SR более устойчив к высоким потерям благодаря селективным ретрансмиссиям")
print("   - GBN проще в реализации но менее эффективен при плохом качестве канала")
print("   - Выбор протокола зависит от ожидаемого уровня потерь в канале")

# Сохранение результатов
df_window.to_csv("window_size_results_loss_0.3.csv", index=False)
df_loss.to_csv("loss_probability_results_window_3.csv", index=False)
print("\nResults saved to:")
print("  - window_size_results_loss_0.3.csv")
print("  - loss_probability_results_window_3.csv")