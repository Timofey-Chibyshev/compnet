import json
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from datetime import datetime
import os
import matplotlib.animation as animation
from typing import List, Dict, Any
import matplotlib.patches as patches

DR_ID = 1000 

class LogVisualizer:
    def __init__(self, log_file: str):
        self.log_file = log_file
        self.events = []
        self.topology = nx.DiGraph()
        self.current_event_index = 0
        self.fig = None
        self.ax = None
        self.simulation_id = ""
        self.topology_type = ""
        self.message_paths = {}
        self.active_messages = {}
        self.anim = None
        self.pos = None
        
    def load_logs(self):
        """Загрузка логов из файла"""
        print(f"Загрузка логов из {self.log_file}...")
        with open(self.log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    event = json.loads(line.strip())
                    self.events.append(event)
                except json.JSONDecodeError as e:
                    print(f"Ошибка чтения строки: {e}")
        
        print(f"Загружено {len(self.events)} событий")
        
        for event in self.events:
            if event['event_type'] == 'TOPOLOGY_CREATED':
                self.topology_type = event['data']['topology_type']
                self.simulation_id = event['simulation_id']
                break

    def extract_topology(self):
        """Извлечение топологии из логов без дублирующих рёбер"""
        print("Извлечение топологии...")

        connections = set()
        for event in self.events:
            if event['event_type'] == 'LINKS_CREATED':
                for conn in event['data']['connections']:
                    if len(conn) >= 2:
                        connections.add(tuple(sorted((conn[0], conn[1]))))

        self.topology.clear()
        for u, v in connections:
            self.topology.add_edge(u, v)

        if len(self.topology.edges()) == 0:
            for event in self.events:
                if event['event_type'] == 'TOPOLOGY_BROADCAST':
                    topology_data = event['data'].get('topology', {})
                    nodes = topology_data.get('nodes', [])
                    edges = topology_data.get('edges', [])
                    self.topology.add_nodes_from(nodes)
                    for edge in edges:
                        if len(edge) >= 2:
                            self.topology.add_edge(edge[0], edge[1])
                    break

        print(f"Топология: {len(self.topology.nodes())} узлов, {len(self.topology.edges())} связей")

        if self.topology_type == "linear":
            self.pos = self._get_linear_positions()
        elif self.topology_type == "ring":
            self.pos = self._get_ring_positions()
        elif self.topology_type == "star":
            self.pos = self._get_star_positions()
        else:
            self.pos = nx.spring_layout(self.topology, seed=42)

    def _get_linear_positions(self):
        """Позиции для линейной топологии"""
        pos = {}
        nodes = sorted([n for n in self.topology.nodes() if n != -1])
        designated_router = -1
        
        for i, node in enumerate(nodes):
            pos[node] = (i * 2, 0)
        
        if designated_router in self.topology.nodes():
            center_x = (len(nodes) - 1) * 2 / 2 if nodes else 0
            pos[designated_router] = (center_x, 2)
        
        return pos
    
    def _get_ring_positions(self):
        """Позиции для кольцевой топологии"""
        pos = {}
        nodes = sorted([n for n in self.topology.nodes() if n != -1])
        designated_router = -1
        
        radius = 3
        for i, node in enumerate(nodes):
            angle = 2 * np.pi * i / len(nodes)
            pos[node] = (radius * np.cos(angle), radius * np.sin(angle))
        
        if designated_router in self.topology.nodes():
            pos[designated_router] = (0, 0)
        
        return pos
    
    def _get_star_positions(self):
        """Позиции для звездообразной топологии"""
        pos = {}
        nodes = sorted([n for n in self.topology.nodes() if n != -1])
        designated_router = -1
        
        if 0 in nodes:
            pos[0] = (0, 0)
            peripheral_nodes = [n for n in nodes if n != 0]
            
            radius = 3
            for i, node in enumerate(peripheral_nodes):
                angle = 2 * np.pi * i / len(peripheral_nodes)
                pos[node] = (radius * np.cos(angle), radius * np.sin(angle))
        else:
            return self._get_ring_positions()
        
        if designated_router in self.topology.nodes():
            pos[designated_router] = (0, 5)
        
        return pos
    
    def visualize_static_topology(self):
        """Статическая визуализация топологии для отчета с правильным DR"""
        if len(self.topology.nodes()) == 0:
            print("Ошибка: топология пуста.")
            return

        plt.figure(figsize=(12, 8))

        dr_edges = []
        router_edges = []
        for u, v in self.topology.edges():
            if u == DR_ID or v == DR_ID:
                dr_edges.append((u, v))
            else:
                router_edges.append((u, v))

        node_colors = ['red' if n == DR_ID else 'skyblue' for n in self.topology.nodes()]
        node_sizes = [2000 if n == DR_ID else 1200 for n in self.topology.nodes()]
        nx.draw_networkx_nodes(self.topology, self.pos, node_color=node_colors, 
                            node_size=node_sizes, edgecolors='black', linewidths=2)

        if dr_edges:
            nx.draw_networkx_edges(self.topology, self.pos, edgelist=dr_edges, 
                                edge_color='red', width=2.5, arrows=True, 
                                arrowsize=25, arrowstyle='-|>', connectionstyle='arc3,rad=0.1')
        if router_edges:
            nx.draw_networkx_edges(self.topology, self.pos, edgelist=router_edges, 
                                edge_color='blue', width=2, arrows=True, 
                                arrowsize=20, arrowstyle='-|>', connectionstyle='arc3,rad=0.05')

        labels = {n: 'DR' if n == DR_ID else f'Router {n}' for n in self.topology.nodes()}
        nx.draw_networkx_labels(self.topology, self.pos, labels, font_size=10, font_weight='bold')

        legend_elements = [
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='red', markersize=10, label='DR'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='skyblue', markersize=10, label='Router'),
            plt.Line2D([0], [0], color='red', lw=2, label='DR Link'),
            plt.Line2D([0], [0], color='blue', lw=2, label='Router Link')
        ]
        plt.legend(handles=legend_elements, loc='upper right', fontsize=10)

        plt.axis('off')
        plt.title(f"Топология сети: {self.topology_type}\nSimulation ID: {self.simulation_id}", fontsize=14)
        plt.tight_layout()

        os.makedirs("topology_plots", exist_ok=True)
        filename = f"topology_plots/{self.simulation_id}_topology.png"
        plt.savefig(filename, dpi=300, bbox_inches='tight')
        print(f"Топология сохранена как: {filename}")
        plt.show()

    def create_animation(self, save_as_gif=False):
        """Создание анимированной визуализации событий"""
        self.fig, self.ax = plt.subplots(figsize=(16, 12))
        
        frames = min(len(self.events), 200)
        
        self.anim = animation.FuncAnimation(
            self.fig, 
            self._update_animation, 
            frames=frames,
            interval=500,
            repeat=True,
            blit=False
        )
        
        plt.tight_layout()
        
        if save_as_gif:
            os.makedirs("visualizations", exist_ok=True)
            gif_path = f"visualizations/{self.simulation_id}_animation.gif"
            self.anim.save(gif_path, writer='pillow', fps=2)
            print(f"Анимация сохранена как: {gif_path}")
        
        plt.show()
        
        return self.anim
    
    def _update_animation(self, frame):
        """Обновление анимации для каждого кадра"""
        self.ax.clear()
        
        if frame >= len(self.events):
            return
        
        current_event = self.events[frame]
        self._process_event(current_event, frame)
        self._draw_topology()
        self._draw_messages(frame)
        self._draw_event_info(current_event, frame)
        self.ax.set_xlim(-6, 6)
        self.ax.set_ylim(-6, 6)
    
    def _process_event(self, event, frame):
        """Обработка события для визуализации"""
        event_type = event['event_type']
        router_id = event.get('router_id')
        data = event.get('data', {})
        
        if event_type == 'HELLO_SENT':
            from_router = data.get('from_router')
            to_neighbor = data.get('to_neighbor')
            if from_router is not None and to_neighbor is not None:
                self._add_message_animation(from_router, to_neighbor, 'HELLO', frame)
        
        elif event_type == 'DATA_SENT':
            destination = data.get('destination')
            next_hop = data.get('next_hop')
            full_path = data.get('full_path', [])
            if router_id is not None and next_hop is not None:
                self._add_message_animation(router_id, next_hop, 'DATA', frame)
                if full_path:
                    self.message_paths[frame] = full_path
        
        elif event_type == 'MESSAGE_FORWARDED':
            next_hop = data.get('next_hop')
            current_path = data.get('current_path', [])
            if router_id is not None and next_hop is not None:
                self._add_message_animation(router_id, next_hop, 'DATA', frame)
                if current_path:
                    self.message_paths[frame] = current_path
        
        elif event_type == 'MESSAGE_DELIVERED':
            path_taken = data.get('path_taken', [])
            if path_taken:
                self.message_paths[frame] = path_taken
    
    def _add_message_animation(self, from_node, to_node, msg_type, frame):
        """Добавление анимации сообщения"""
        message_id = f"{from_node}_{to_node}_{msg_type}_{frame}"
        self.active_messages[message_id] = {
            'from': from_node,
            'to': to_node,
            'type': msg_type,
            'progress': 0.0,
            'start_frame': frame
        }
        
    def _draw_topology(self):
        """Отрисовка топологии с выделением DR и его соединений"""
        node_colors = ['red' if n == DR_ID else 'lightblue' for n in self.topology.nodes()]
        node_sizes = [2000 if n == DR_ID else 1200 for n in self.topology.nodes()]

        nx.draw_networkx_nodes(self.topology, self.pos, node_color=node_colors, 
                            node_size=node_sizes, alpha=0.9, edgecolors='black', 
                            linewidths=2, ax=self.ax)

        dr_edges = []
        router_edges = []
        for u, v in self.topology.edges():
            if u == DR_ID or v == DR_ID:
                dr_edges.append((u, v))
            else:
                router_edges.append((u, v))

        if dr_edges:
            nx.draw_networkx_edges(self.topology, self.pos, edgelist=dr_edges,
                                edge_color='red', width=2.5, alpha=0.8,
                                arrows=True, arrowsize=25, arrowstyle='->',
                                connectionstyle='arc3,rad=0.1', ax=self.ax)

        if router_edges:
            nx.draw_networkx_edges(self.topology, self.pos, edgelist=router_edges,
                                edge_color='blue', width=1.5, alpha=0.6,
                                arrows=True, arrowsize=20, arrowstyle='->',
                                connectionstyle='arc3,rad=0.05', ax=self.ax)

        labels = {n: ('DR' if n == DR_ID else f'Router {n}') for n in self.topology.nodes()}
        nx.draw_networkx_labels(self.topology, self.pos, labels, font_size=10, font_weight='bold', ax=self.ax)

    def _draw_messages(self, current_frame):
        """Отрисовка активных сообщений с выделением сообщений от DR"""
        messages_to_remove = []
        
        for msg_id, msg_data in self.active_messages.items():
            from_node = msg_data['from']
            to_node = msg_data['to']
            msg_type = msg_data['type']
            
            msg_data['progress'] += 0.1
            
            if msg_data['progress'] >= 1.0:
                messages_to_remove.append(msg_id)
                continue
            
            if from_node in self.pos and to_node in self.pos:
                start_pos = self.pos[from_node]
                end_pos = self.pos[to_node]
                
                current_x = start_pos[0] + (end_pos[0] - start_pos[0]) * msg_data['progress']
                current_y = start_pos[1] + (end_pos[1] - start_pos[1]) * msg_data['progress']
                
                if from_node == -1:
                    color = 'red'
                else:
                    color = 'blue' if msg_type == 'DATA' else 'green'
                
                marker = 'o' if msg_type == 'DATA' else 's'
                size = 100 if msg_type == 'DATA' else 80
                
                self.ax.scatter(current_x, current_y, c=color, marker=marker, s=size, alpha=0.8)
                
                if msg_type == 'DATA':
                    self.ax.text(current_x, current_y + 0.3, "DATA", fontsize=8, 
                                ha='center', va='bottom', color=color)
        
        for msg_id in messages_to_remove:
            del self.active_messages[msg_id]
    
    def _draw_event_info(self, event, frame):
        """Отрисовка информации о событии"""
        event_type = event['event_type']
        timestamp = event['timestamp']
        router_id = event.get('router_id', 'N/A')
        data = event.get('data', {})
        
        info_text = f"Событие {frame + 1}/{len(self.events)}\n"
        info_text += f"Тип: {event_type}\n"
        info_text += f"Время: {timestamp[11:19]}\n"
        info_text += f"Маршрутизатор: {router_id}"
        
        if event_type == 'DATA_SENT':
            info_text += f"\nНазначение: {data.get('destination', 'N/A')}"
        elif event_type == 'HELLO_SENT':
            info_text += f"\nСосед: {data.get('to_neighbor', 'N/A')}"
        elif event_type == 'DISCONNECT_SIMULATED':
            info_text += f"\nРазрыв: {data.get('router1', '')}-{data.get('router2', '')}"
        
        self.ax.text(0.02, 0.98, info_text, 
                   transform=self.ax.transAxes, fontsize=10,
                   verticalalignment='top',
                   bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.9))
        
        self.ax.set_title(f"Симуляция OSPF - Топология: {self.topology_type}\n"
                         f"Simulation ID: {self.simulation_id}", 
                         fontsize=12, fontweight='bold')
        
        legend_elements = [
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='blue', markersize=8, label='DATA'),
            plt.Line2D([0], [0], marker='s', color='w', markerfacecolor='green', markersize=8, label='HELLO'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='red', markersize=8, label='DR'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='lightblue', markersize=8, label='Router')
        ]
        self.ax.legend(handles=legend_elements, loc='upper right', bbox_to_anchor=(0.98, 0.98))
    
    def generate_event_timeline(self):
        """Генерация временной линии событий"""
        fig, ax = plt.subplots(figsize=(15, 8))
        
        event_types = {}
        for event in self.events:
            event_type = event['event_type']
            if event_type not in event_types:
                event_types[event_type] = []
            event_types[event_type].append(event)
        
        colors = plt.cm.Set3(np.linspace(0, 1, len(event_types)))
        
        start_time = None
        for i, (event_type, events) in enumerate(event_types.items()):
            times = []
            for event in events:
                event_time = datetime.fromisoformat(event['timestamp'])
                if start_time is None:
                    start_time = event_time
                delta = (event_time - start_time).total_seconds()
                times.append(delta)
            
            ax.scatter(times, [i] * len(times), 
                     c=[colors[i]], label=event_type, 
                     alpha=0.7, s=50)
        
        ax.set_yticks(range(len(event_types)))
        ax.set_yticklabels(list(event_types.keys()))
        ax.set_xlabel('Время от начала симуляции (секунды)')
        ax.set_title('Временная линия событий')
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.show()
    
    def analyze_message_flow(self):
        """Анализ потока сообщений"""
        print(f"\n=== АНАЛИЗ ПОТОКА СООБЩЕНИЙ ===")
        print(f"Всего событий: {len(self.events)}")
        
        event_types = {}
        for event in self.events:
            event_type = event['event_type']
            event_types[event_type] = event_types.get(event_type, 0) + 1
        
        print("\nТипы событий:")
        for event_type, count in sorted(event_types.items(), key=lambda x: x[1], reverse=True):
            print(f"  {event_type}: {count}")
        
        message_events = [e for e in self.events if 'message' in str(e)]
        print(f"\nСобытий с сообщениями: {len(message_events)}")
        
        delivered_messages = [e for e in self.events if e['event_type'] == 'MESSAGE_DELIVERED']
        print(f"Успешно доставленных сообщений: {len(delivered_messages)}")
        
        failed_sends = [e for e in self.events if e['event_type'] == 'DATA_SEND_FAILED']
        print(f"Неудачных отправок: {len(failed_sends)}")
        
        topology_changes = [e for e in self.events if e['event_type'] == 'DISCONNECT_SIMULATED']
        print(f"Изменений топологии: {len(topology_changes)}")

def main():
    """Основная функция скрипта визуализации"""
    log_dir = "simulation_logs"
    if not os.path.exists(log_dir):
        print(f"Папка {log_dir} не существует!")
        return
    
    log_files = [f for f in os.listdir(log_dir) if f.endswith('.json')]
    
    if not log_files:
        print(f"Нет файлов логов в папке {log_dir}")
        return
    
    print("Доступные файлы логов:")
    for i, file in enumerate(log_files):
        file_path = os.path.join(log_dir, file)
        with open(file_path, 'r') as f:
            first_line = f.readline()
            try:
                first_event = json.loads(first_line)
                topology_type = first_event.get('data', {}).get('topology_type', 'unknown')
                print(f"{i + 1}. {file} (Топология: {topology_type})")
            except:
                print(f"{i + 1}. {file}")
    
    try:
        choice = int(input("\nВыберите файл лога для визуализации: ")) - 1
        if choice < 0 or choice >= len(log_files):
            print("Неверный выбор, используется первый файл")
            choice = 0
        selected_file = log_files[choice]
    except (ValueError, IndexError):
        print("Неверный выбор, используется первый файл")
        selected_file = log_files[0]
    
    log_path = os.path.join(log_dir, selected_file)
    visualizer = LogVisualizer(log_path)
    visualizer.load_logs()
    visualizer.extract_topology()
    
    while True:
        print("\n" + "="*50)
        print("ВИЗУАЛИЗАТОР СЕТЕВЫХ ЛОГОВ OSPF")
        print("="*50)
        print("1. Статическая визуализация топологии")
        print("2. Анимированная визуализация событий")
        print("3. Анимированная визуализация (сохранить как GIF)")
        print("4. Временная линия событий")
        print("5. Анализ потока сообщений")
        print("6. Выход")
        
        choice = input("Выберите опцию (1-6): ").strip()
        
        if choice == '1':
            visualizer.visualize_static_topology()
        
        elif choice == '2':
            print("Создание анимации... (может занять некоторое время)")
            print("Закройте окно анимации чтобы продолжить...")
            visualizer.create_animation(save_as_gif=False)
        
        elif choice == '3':
            print("Создание анимации и сохранение как GIF...")
            visualizer.create_animation(save_as_gif=True)
        
        elif choice == '4':
            visualizer.generate_event_timeline()
        
        elif choice == '5':
            visualizer.analyze_message_flow()
        
        elif choice == '6':
            break
        
        else:
            print("Неверный выбор, попробуйте снова")

if __name__ == "__main__":
    main()
