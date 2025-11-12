import threading
import time
import random
import networkx as nx
from enum import Enum
from typing import List, Dict, Any, Optional
import queue
import json
import os
from datetime import datetime

class MessageType(Enum):
    HELLO = "HELLO"
    GET_NEIGHBORS = "GET_NEIGHBORS"
    SET_NEIGHBORS = "SET_NEIGHBORS"
    SET_TOPOLOGY = "SET_TOPOLOGY"
    DATA = "DATA"
    DISCONNECT = "DISCONNECT"

class Message:
    def __init__(self, source_id: int, dest_id: Optional[int], msg_type: MessageType, data: Any = None):
        self.source_id = source_id
        self.dest_id = dest_id
        self.type = msg_type
        self.data = data
        self.timestamp = time.time()
        self.message_id = f"{source_id}_{time.time()}_{random.randint(1000, 9999)}"
    
    def __str__(self):
        return f"Message({self.source_id}->{self.dest_id}, {self.type}, {self.data})"
    
    def to_dict(self):
        return {
            "message_id": self.message_id,
            "source_id": self.source_id,
            "dest_id": self.dest_id,
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp
        }

class Link:
    """Канал связи между двумя маршрутизаторами"""
    def __init__(self, router1_id: int, router2_id: int, delay: float = 0.1):
        self.router1_id = router1_id
        self.router2_id = router2_id
        self.delay = delay
        self.message_queue = queue.Queue()
        self.active = True
        self.message_count = 0
        # блокировка для атомарной проверки состояния
        self.lock = threading.Lock()
    
    def send(self, message: Message):
        with self.lock:
            if not self.active:
                return
            self.message_count += 1
        # Имитация задержки сети
        def delayed_put():
            time.sleep(self.delay)
            with self.lock:
                if self.active:
                    self.message_queue.put(message)
        threading.Thread(target=delayed_put, daemon=True).start()
    
    def receive(self) -> Optional[Message]:
        try:
            return self.message_queue.get_nowait()
        except queue.Empty:
            return None

class Router:
    def __init__(self, router_id: int, designated_router_id: int = -1, simulator=None):
        self.id = router_id
        self.designated_router_id = designated_router_id
        self.simulator = simulator
        self.links: Dict[int, Link] = {}  # neighbor_id -> Link
        self.neighbors: List[int] = []  # всегда хранит список id соседей (ints). FIXED
        self.topology = None
        self.shortest_paths: Dict[int, List[int]] = {}
        self.message_log = []
        self.running = True
        self.message_count = 0
        self.hello_received = []
        
        # Поток для обработки входящих сообщений
        self.thread = threading.Thread(target=self._process_messages)
        self.thread.daemon = True
    
    def add_link(self, neighbor_id: int, link: Link):
        self.links[neighbor_id] = link
    
    def start(self):
        self.thread.start()
        # Отправляем HELLO-пакеты всем соседям
        self._send_hello_messages()
    
    def stop(self):
        self.running = False
        # даём немного времени потоку завершиться
        if self.thread.is_alive():
            self.thread.join(timeout=1)
    
    def _send_hello_messages(self):
        """Отправка HELLO-пакетов только соседям-роутерам, не DR"""
        for neighbor_id in list(self.links.keys()):
            # Пропускаем служебный DR
            if self.simulator and neighbor_id == self.simulator.designated_router.id:
                continue
            hello_msg = Message(
                source_id=self.id,
                dest_id=neighbor_id,
                msg_type=MessageType.HELLO,
                data={"sent_time": time.time()}
            )
            self._send_to_neighbor(neighbor_id, hello_msg)
            if self.simulator:
                self.simulator._log_message_event(hello_msg, "HELLO_SENT", {
                    "from_router": self.id,
                    "to_router": neighbor_id
                })
            self._log("SEND_HELLO", {"to_router": neighbor_id})

    
    def _send_to_neighbor(self, neighbor_id: int, message: Message):
        if neighbor_id in self.links:
            self.message_count += 1
            self.links[neighbor_id].send(message)
        else:
            # Попытка отправить по несуществующему линку — логируем
            self._log("SEND_FAILED_NO_LINK", {
                "attempted_to": neighbor_id,
                "message": message.to_dict()
            })
    
    def _process_messages(self):
        while self.running:
            for neighbor_id, link in list(self.links.items()):
                message = link.receive()
                if message:
                    # Некоторые сообщения (например HELLO) приходят с dest конкретным neighbor_id,
                    # поэтому проверяем адресность внутри _handle_message
                    self._handle_message(message)
            time.sleep(0.05)
    
    def _handle_message(self, message: Message):
        # При адресованных сообщениях отбрасываем не для нас (кроме HELLO — считаем, что HELLO может считаться локальным установлением соседства)
        if message.dest_id is not None and message.dest_id != self.id:
            if message.type != MessageType.HELLO:
                # игнорируем
                return
                
        if self.simulator:
            self.simulator._log_message_event(message, "MESSAGE_RECEIVED", {
                "by_router": self.id
            })
        
        self._log("RECEIVE_MESSAGE", {
            "from_router": message.source_id,
            "message_type": message.type.value,
            "message_id": message.message_id
        })
        
        if message.type == MessageType.HELLO:
            self._handle_hello(message)
        elif message.type == MessageType.GET_NEIGHBORS:
            self._handle_get_neighbors(message)
        elif message.type == MessageType.SET_NEIGHBORS:
            self._handle_set_neighbors(message)
        elif message.type == MessageType.SET_TOPOLOGY:
            self._handle_set_topology(message)
        elif message.type == MessageType.DATA:
            self._handle_data(message)
        elif message.type == MessageType.DISCONNECT:
            self._handle_disconnect(message)
        else:
            self._log("UNKNOWN_MESSAGE_TYPE", {"type": str(message.type)})
    
    def _handle_hello(self, message: Message):
        """Обработка HELLO-пакета"""
        if message.source_id == self.id:
            return
        if message.source_id not in self.hello_received:
            self.hello_received.append(message.source_id)
            # Поддерживаем также список neighbors как список id (если линк доступен)
            if message.source_id not in self.neighbors and message.source_id in self.links:
                self.neighbors.append(message.source_id)
            if self.simulator:
                self.simulator._log_router_event(self.id, "HELLO_RECEIVED", {
                    "from_router": message.source_id,
                    "current_hello_list": self.hello_received.copy()
                })
            self._log("HELLO_RECEIVED", {
                "from_router": message.source_id,
                "current_hello_list": self.hello_received.copy()
            })
    
    def _handle_get_neighbors(self, message: Message):
        """Отправка информации о соседях выделенному маршрутизатору"""
        # Формируем список соседей в формате, который ожидает DR: список словарей
        neighbors_info = []
        for neighbor_id in self.hello_received:
            if neighbor_id in self.links:
                transmission_time = self.links[neighbor_id].delay if hasattr(self.links[neighbor_id], "delay") else 0.1
                neighbors_info.append({
                    "neighbor_id": neighbor_id,
                    "transmission_time": transmission_time
                })
        response = Message(
            source_id=self.id,
            dest_id=self.designated_router_id,
            msg_type=MessageType.SET_NEIGHBORS,
            data=neighbors_info
        )
        # отправляем к DR (предполагается, что у роутера есть линк к DR)
        self._send_to_neighbor(self.designated_router_id, response)
        if self.simulator:
            self.simulator._log_message_event(response, "SET_NEIGHBORS_SENT", {
                "from_router": self.id,
                "to_router": self.designated_router_id,
                "neighbors_info": neighbors_info
            })
        self._log("SET_NEIGHBORS_SENT", {
            "to_router": self.designated_router_id,
            "neighbors_info": neighbors_info,
            "message_id": response.message_id
        })
    
    def _handle_set_neighbors(self, message: Message):
        """Если роутеру прилетает подтверждение соседей (может использоваться DR) — приводим к list[int]"""
        data = message.data
        if isinstance(data, list):
            # возможны два формата: список id или список dicts
            if len(data) > 0 and isinstance(data[0], dict):
                self.neighbors = [d["neighbor_id"] for d in data]
            else:
                # список id
                self.neighbors = list(data)
        else:
            self.neighbors = []
        if self.simulator:
            self.simulator._log_router_event(self.id, "NEIGHBORS_CONFIRMED", {
                "confirmed_neighbors": self.neighbors
            })
        self._log("NEIGHBORS_CONFIRMED", {
            "confirmed_neighbors": self.neighbors
        })
    
    def _handle_set_topology(self, message: Message):
        """Получение топологии сети и вычисление кратчайших путей"""
        topology_data = message.data
        G = nx.Graph()
        # создаём все узлы
        for node in topology_data["nodes"]:
            G.add_node(node)
        # создаём все рёбра
        for edge in topology_data["edges"]:
            u, v, weight = edge
            G.add_edge(u, v, weight=weight)
        self.topology = G

        # логирование
        if self.simulator:
            self.simulator._log_router_event(self.id, "TOPOLOGY_RECEIVED", {
                "topology_nodes": list(self.topology.nodes()),
                "topology_edges": [(u, v, d['weight']) for u, v, d in self.topology.edges(data=True)]
            })
        self._log("TOPOLOGY_RECEIVED", {
            "topology_nodes": list(self.topology.nodes()),
            "topology_edges": [(u, v, d['weight']) for u, v, d in self.topology.edges(data=True)]
        })

        # пересчёт кратчайших путей
        self._calculate_shortest_paths()
    
    def _calculate_shortest_paths(self):
        """Вычисление кратчайших путей с защитой от недоступных узлов"""
        if self.topology is None or len(self.topology.nodes) == 0:
            self.shortest_paths = {}
            self._log("PATH_CALCULATION_ERROR", {"error": "Topology is empty"})
            return

        try:
            paths = nx.single_source_dijkstra_path(self.topology, self.id)
            self.shortest_paths = paths
            self._log("SHORTEST_PATHS_CALCULATED", {"paths": {str(k): v for k, v in paths.items()}})
            if self.simulator:
                self.simulator._log_router_event(self.id, "SHORTEST_PATHS_CALCULATED",
                                                {"paths": {str(k): v for k, v in paths.items()}})
        except nx.NetworkXNoPath:
            self.shortest_paths = {}
            self._log("PATH_CALCULATION_ERROR", {"error": "No path to some nodes"})
            if self.simulator:
                self.simulator._log_router_event(self.id, "PATH_CALCULATION_ERROR", {"error": "No path to some nodes"})
        except Exception as e:
            self.shortest_paths = {}
            self._log("PATH_CALCULATION_ERROR", {"error": str(e)})
            if self.simulator:
                self.simulator._log_router_event(self.id, "PATH_CALCULATION_ERROR", {"error": str(e)})
    
    def _handle_data(self, message: Message):
        """Обработка DATA-сообщений"""
        if message.dest_id == self.id:
            # Сообщение дошло до адресата
            if self.simulator:
                self.simulator._log_message_event(message, "MESSAGE_DELIVERED", {
                    "final_destination": self.id,
                    "path_taken": message.data
                })
            self._log("MESSAGE_DELIVERED", {
                "original_source": message.source_id,
                "path_taken": message.data,
                "final_destination": self.id
            })
        else:
            # Пересылаем сообщение дальше по кратчайшему пути
            if message.dest_id in self.shortest_paths:
                path = self.shortest_paths[message.dest_id]
                if len(path) > 1:
                    next_hop = path[1]
                    if isinstance(message.data, list):
                        new_data = message.data + [self.id]
                    else:
                        new_data = [self.id]
                    forward_msg = Message(
                        source_id=message.source_id,
                        dest_id=message.dest_id,
                        msg_type=MessageType.DATA,
                        data=new_data
                    )
                    self._send_to_neighbor(next_hop, forward_msg)
                    if self.simulator:
                        self.simulator._log_message_event(forward_msg, "MESSAGE_FORWARDED", {
                            "original_source": message.source_id,
                            "final_destination": message.dest_id,
                            "next_hop": next_hop,
                            "current_path": new_data
                        })
                    self._log("MESSAGE_FORWARDED", {
                        "original_source": message.source_id,
                        "final_destination": message.dest_id,
                        "next_hop": next_hop,
                        "current_path": new_data,
                        "message_id": forward_msg.message_id
                    })
                else:
                    # уже на месте?
                    self._log("DATA_AT_DESTINATION", {"dest": message.dest_id})
            else:
                if self.simulator:
                    self.simulator._log_message_event(message, "MESSAGE_UNDELIVERABLE", {
                        "reason": "No path available"
                    })
                self._log("MESSAGE_UNDELIVERABLE", {
                    "original_source": message.source_id,
                    "final_destination": message.dest_id,
                    "reason": "No path available"
                })
        
    def _handle_disconnect(self, message: Message):
        """Обработка разрыва связи. message.data = id соседа, который стал недоступен"""
        router_to_disconnect = message.data

        # Деактивируем линк
        link = self.links.get(router_to_disconnect)
        if link:
            with link.lock:
                link.active = False

        # Удаляем роутер из соседей и hello_received
        self.neighbors = [r for r in self.neighbors if r != router_to_disconnect]
        self.hello_received = [r for r in self.hello_received if r != router_to_disconnect]

        # Логирование
        log_data = {
            "disconnected_router": router_to_disconnect,
            "remaining_neighbors": self.neighbors.copy(),
            "remaining_hello": self.hello_received.copy()
        }
        self._log("LINK_DISCONNECTED", log_data)
        if self.simulator:
            self.simulator._log_router_event(self.id, "LINK_DISCONNECTED", log_data)

        # Пересчёт кратчайших путей безопасно
        self._calculate_shortest_paths()
    
    def send_data(self, dest_id: int, data: Any):
        """Отправка данных другому маршрутизатору"""
        if dest_id in self.shortest_paths:
            path = self.shortest_paths[dest_id]
            if len(path) > 1:
                next_hop = path[1]
                message = Message(
                    source_id=self.id,
                    dest_id=dest_id,
                    msg_type=MessageType.DATA,
                    data=[self.id] if not isinstance(data, list) else data
                )
                self._send_to_neighbor(next_hop, message)
                if self.simulator:
                    self.simulator._log_message_event(message, "DATA_SENT", {
                        "destination": dest_id,
                        "next_hop": next_hop,
                        "full_path": path
                    })
                self._log("DATA_SENT", {
                    "destination": dest_id,
                    "next_hop": next_hop,
                    "full_path": path,
                    "message_id": message.message_id
                })
        else:
            if self.simulator:
                self.simulator._log_router_event(self.id, "DATA_SEND_FAILED", {
                    "destination": dest_id,
                    "reason": "No path available"
                })
            self._log("DATA_SEND_FAILED", {
                "destination": dest_id,
                "reason": "No path available"
            })
    
    def _log(self, event_type: str, data: Dict):
        """Улучшенное логирование с структурными данными"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "router_id": self.id,
            "event_type": event_type,
            "data": data
        }
        self.message_log.append(log_entry)
        print(f"[{log_entry['timestamp']}] Router {self.id}: {event_type} - {data}")

class DesignatedRouter(Router):
    def __init__(self, simulator=None):
        super().__init__(router_id=1000, designated_router_id=1000, simulator=simulator)
        self.network_topology = nx.Graph()
        self.all_routers = []
        self.neighbor_info = {}
        self.topology_changes = 0
    
    def add_router(self, router_id: int):
        if router_id not in self.all_routers:
            self.all_routers.append(router_id)
            self.network_topology.add_node(router_id)
            if self.simulator:
                self.simulator._log_router_event(self.id, "ROUTER_ADDED", {
                    "router_id": router_id,
                    "total_routers": self.all_routers.copy()
                })
            self._log("ROUTER_ADDED", {
                "router_id": router_id,
                "total_routers": self.all_routers.copy()
            })
    
    def start(self):
        super().start()
        threading.Thread(target=self._request_neighbors, daemon=True).start()
    
    def _request_neighbors(self):
        """Запрос информации о соседях у всех маршрутизаторов с ожиданием ответов"""
        time.sleep(2)  # даём время на HELLO
        self.neighbor_info = {}
        for router_id in self.all_routers:
            if router_id != self.id:
                message = Message(
                    source_id=self.id,
                    dest_id=router_id,
                    msg_type=MessageType.GET_NEIGHBORS
                )
                self._send_to_neighbor(router_id, message)
                if self.simulator:
                    self.simulator._log_message_event(message, "NEIGHBORS_REQUEST_SENT", {
                        "to_router": router_id
                    })
                self._log("NEIGHBORS_REQUEST_SENT", {
                    "to_router": router_id,
                    "message_id": message.message_id
                })
        start_time = time.time()
        timeout = 8
        while len(self.neighbor_info) < len(self.all_routers) - 1:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                missing = set(self.all_routers) - {self.id} - set(self.neighbor_info.keys())
                for missing_id in missing:
                    self.neighbor_info[missing_id] = []
                break
            time.sleep(0.5)
        self._broadcast_topology()
    
    def _handle_set_neighbors(self, message: Message):
        """Получение информации о соседях от маршрутизаторов"""
        router_id = message.source_id
        neighbors_info = message.data  # список словарей {"neighbor_id":..., "transmission_time":...}
        self.neighbor_info[router_id] = neighbors_info
        # добавляем рёбра в топологию
        for neighbor in neighbors_info:
            neighbor_id = neighbor["neighbor_id"]
            weight = neighbor.get("transmission_time", 0.1)
            if not self.network_topology.has_edge(router_id, neighbor_id):
                self.network_topology.add_edge(router_id, neighbor_id, weight=weight)
        if self.simulator:
            self.simulator._log_router_event(self.id, "NEIGHBOR_INFO_RECEIVED", {
                "from_router": router_id,
                "neighbors": neighbors_info,
                "current_topology_edges": [(u, v, d['weight']) for u, v, d in self.network_topology.edges(data=True)]
            })
        self._log("NEIGHBOR_INFO_RECEIVED", {
            "from_router": router_id,
            "neighbors": neighbors_info,
            "current_topology_edges": [(u, v, d['weight']) for u, v, d in self.network_topology.edges(data=True)]
        })
        if len(self.neighbor_info) == len(self.all_routers) - 1:
            self._broadcast_topology()
            
    def _broadcast_topology(self, custom_topology: Optional[dict] = None):
        """Рассылка топологии всем маршрутизаторам.
        Если передана custom_topology — используется она вместо self.network_topology.
        """
        # Формируем данные топологии
        if custom_topology is not None:
            topology_data = custom_topology
        else:
            # Если топология пуста — создаём резервную (линейную)
            if len(self.network_topology.edges()) == 0:
                nodes = self.all_routers.copy()
                for i in range(len(nodes) - 1):
                    self.network_topology.add_edge(nodes[i], nodes[i + 1], weight=0.1)

            # Подготавливаем данные топологии для отправки
            topology_data = {
                "nodes": list(self.network_topology.nodes()),  # включаем DR
                "edges": [(u, v, d.get("weight", 1)) for u, v, d in self.network_topology.edges(data=True)]
            }

        # Обновляем локальную топологию DR (для внутреннего хранения)
        self.network_topology.clear()
        self.network_topology.add_nodes_from(topology_data["nodes"])
        for u, v, w in topology_data["edges"]:
            self.network_topology.add_edge(u, v, weight=w)

        # Рассылаем топологию всем маршрутизаторам, кроме DR
        for router_id in self.all_routers:
            if router_id != self.id:
                message = Message(
                    source_id=self.id,
                    dest_id=router_id,
                    msg_type=MessageType.SET_TOPOLOGY,
                    data=topology_data,
                )
                self._send_to_neighbor(router_id, message)

        # Логирование
        if self.simulator:
            self.simulator._log_topology_event("TOPOLOGY_BROADCAST", {"topology": topology_data})
        self._log("TOPOLOGY_BROADCAST", {"topology": topology_data})
    
    def simulate_disconnect(self, router1_id: int, router2_id: int):
        """Имитация разрыва связи между двумя маршрутизаторами с обновлением топологии всех роутеров"""
        edge_removed = False
        if self.network_topology.has_edge(router1_id, router2_id):
            self.network_topology.remove_edge(router1_id, router2_id)
            edge_removed = True

        # Отправляем DISCONNECT всем участникам
        for r1, r2 in [(router1_id, router2_id), (router2_id, router1_id)]:
            if r1 in self.simulator.routers:
                msg = Message(
                    source_id=self.id,
                    dest_id=r1,
                    msg_type=MessageType.DISCONNECT,
                    data=r2
                )
                self._send_to_neighbor(r1, msg)

        time.sleep(0.5)

        # Обновляем топологию для всех роутеров
        for router in self.simulator.routers.values():
            if router.id != self.id and router.topology is not None:
                router.topology = self.network_topology.copy()
                router._calculate_shortest_paths()

        self.topology_changes += 1
        log_data = {
            "router1": router1_id,
            "router2": router2_id,
            "edge_removed": edge_removed,
            "topology_change_count": self.topology_changes,
            "current_topology_edges": [(u, v, d['weight']) for u, v, d in self.network_topology.edges(data=True)]
        }
        self._log("DISCONNECT_SIMULATED", log_data)
        if self.simulator:
            self.simulator._log_topology_event("DISCONNECT_SIMULATED", log_data)

class NetworkSimulator:
    """Класс для создания и управления сетевой симуляцией"""
    def __init__(self):
        self.routers = {}
        self.links = {}  # key: (a,b) -> Link (сохраняем обе пары (a,b) и (b,a) на одну ссылку). FIXED
        self.designated_router = None
        self.topology_type = ""
        self.simulation_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.event_counter = 0
        os.makedirs("simulation_logs", exist_ok=True)
        self.log_file = f"simulation_logs/simulation_{self.simulation_id}.json"
    
    def _log_topology_event(self, event_type: str, data: Dict):
        log_entry = {
            "event_id": self.event_counter,
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "simulation_id": self.simulation_id,
            "topology_type": self.topology_type,
            "data": data
        }
        self.event_counter += 1
        self._write_log(log_entry)
    
    def _log_router_event(self, router_id: int, event_type: str, data: Dict):
        log_entry = {
            "event_id": self.event_counter,
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "simulation_id": self.simulation_id,
            "router_id": router_id,
            "data": data
        }
        self.event_counter += 1
        self._write_log(log_entry)
    
    def _log_message_event(self, message: Message, event_type: str, additional_data: Dict = None):
        data = {
            "message": message.to_dict(),
            **(additional_data if additional_data else {})
        }
        log_entry = {
            "event_id": self.event_counter,
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "simulation_id": self.simulation_id,
            "data": data
        }
        self.event_counter += 1
        self._write_log(log_entry)
    
    def create_linear_topology(self, num_routers: int = 5):
        self.topology_type = "linear"
        self.designated_router = DesignatedRouter(self)
        self.routers[self.designated_router.id] = self.designated_router
        self.designated_router.add_router(self.designated_router.id)

        for i in range(num_routers):
            router = Router(i, self.designated_router.id, self)
            self.routers[i] = router
            self.designated_router.add_router(i)

        connections = []
        for i in range(num_routers - 1):
            link = Link(i, i + 1, delay=0.05)
            self.routers[i].add_link(i + 1, link)
            self.routers[i + 1].add_link(i, link)
            self._store_link(i, i + 1, link)
            connections.append((i, i + 1))

        for i in range(num_routers):
            link_dr = Link(i, self.designated_router.id, delay=0.05)
            self.routers[i].add_link(self.designated_router.id, link_dr)
            self.designated_router.add_link(i, link_dr)
            self._store_link(i, self.designated_router.id, link_dr)
            connections.append((i, self.designated_router.id))

        self._log_topology_event("LINKS_CREATED", {"connections": connections})

        self.designated_router._broadcast_topology()

    def create_ring_topology(self, num_routers: int = 5):
        self.topology_type = "ring"

        # создаём выделенный маршрутизатор (DR)
        self.designated_router = DesignatedRouter(self)
        self.routers[self.designated_router.id] = self.designated_router
        self.designated_router.add_router(self.designated_router.id)

        # создаём обычные маршрутизаторы
        for i in range(num_routers):
            router = Router(i, self.designated_router.id, self)
            self.routers[i] = router
            self.designated_router.add_router(i)

        connections = []

        # соединяем обычные маршрутизаторы в кольцо
        for i in range(num_routers):
            next_i = (i + 1) % num_routers  # замыкаем кольцо
            link = Link(i, next_i, delay=0.1)
            self.routers[i].add_link(next_i, link)
            self.routers[next_i].add_link(i, link)
            self._store_link(i, next_i, link)
            connections.append((i, next_i, 0.1))

        # связываем всех с DR
        for i in range(num_routers):
            link_dr = Link(i, self.designated_router.id, delay=0.05)
            self.routers[i].add_link(self.designated_router.id, link_dr)
            self.designated_router.add_link(i, link_dr)
            self._store_link(i, self.designated_router.id, link_dr)
            connections.append((i, self.designated_router.id, 0.05))

        # логируем топологию
        self._log_topology_event("LINKS_CREATED", {"connections": connections})

        # формируем кастомную топологию без самого DR
        custom_topology = {
            "nodes": [i for i in range(num_routers)],
            "edges": [(u, v, w) for (u, v, w) in connections if u != self.designated_router.id and v != self.designated_router.id]
        }

        # DR рассылает топологию всем маршрутизаторам
        self.designated_router._broadcast_topology(custom_topology=custom_topology)

    def create_star_topology(self, num_routers: int = 5):
        self.topology_type = "star"
        self.designated_router = DesignatedRouter(-1, self)
        self.routers[-1] = self.designated_router
        self.designated_router.add_router(-1)
        for i in range(num_routers):
            router = Router(i, -1, self)
            self.routers[i] = router
            self.designated_router.add_router(i)
        connections = []
        center_id = 0
        for i in range(1, num_routers):
            if (center_id, i) not in self.links and (i, center_id) not in self.links:
                link = Link(center_id, i, delay=0.05)
                self.routers[center_id].add_link(i, link)
                self.routers[i].add_link(center_id, link)
                self._store_link(center_id, i, link)
                connections.append((center_id, i))
        for i in range(num_routers):
            if (i, -1) not in self.links:
                link_dr = Link(i, -1, delay=0.05)
                self.routers[i].add_link(-1, link_dr)
                self.designated_router.add_link(i, link_dr)
                self._store_link(i, -1, link_dr)
                connections.append((i, -1))
        self._log_topology_event("LINKS_CREATED", {
            "connections": connections,
            "total_links": len(connections)
        })
        self._log_topology_event("SIMULATION_READY", {
            "total_routers": len(self.routers),
            "total_links": len(self.links)
        })
    
    def _store_link(self, router1_id: int, router2_id: int, link: Link):
        """Сохраняем ссылку на канал связи для последующего доступа.
           FIXED: сохраняем обе пары (a,b) и (b,a) указывая на один объект Link."""
        self.links[(router1_id, router2_id)] = link
        self.links[(router2_id, router1_id)] = link  # обратный ключ тоже
    
    def _write_log(self, log_entry):
        with open(self.log_file, "a", encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    
    def start_simulation(self):
        for router in self.routers.values():
            router.start()
        print(f"Сетевая симуляция запущена (топология: {self.topology_type})")
        print(f"Логи сохраняются в: {self.log_file}")
        # даём время на установку соседства и сбор топологии
        time.sleep(16)
        self._test_data_transfer()
        
    def _test_data_transfer(self):
        self._write_log({
            "event_id": self.event_counter,
            "timestamp": datetime.now().isoformat(),
            "event_type": "TEST_DATA_TRANSFER_START",
            "simulation_id": self.simulation_id,
            "topology_type": self.topology_type,
            "data": {}
        })
        self.event_counter += 1
        print("\n--- Тестирование передачи данных ---")
        if self.designated_router and len(self.designated_router.network_topology.edges()) == 0:
            print("ПРЕДУПРЕЖДЕНИЕ: Топология пустая! Передача данных невозможна.")
            return

        # Пример: для линейной, кольца и звезды отправляем 0 -> max (num-1)
        if self.topology_type in ("linear", "ring", "star"):
            ids = sorted([
                r for r in self.routers.keys()
                if r not in (-1, self.designated_router.id)
            ])
            if len(ids) >= 2:
                src = ids[0]
                dst = ids[-1]
                if dst in self.routers[src].shortest_paths:
                    print(f"Router {src} отправляет данные Router {dst}")
                    self.routers[src].send_data(dst, "Test message")
                else:
                    print(f"ПРЕДУПРЕЖДЕНИЕ: Нет пути от Router {src} до Router {dst}")
        time.sleep(2)

        # Симулируем разрыв для линейной топологии
        if self.topology_type == "linear":
            print("\n--- Имитация разрыва связи (1-2) ---")
            self.designated_router.simulate_disconnect(1, 2)
            time.sleep(2)
            print("\n--- Тестирование после разрыва ---")
            ids = sorted([
                r for r in self.routers.keys()
                if r not in (-1, self.designated_router.id)
            ])
            if len(ids) >= 2:
                src = ids[0]
                dst = ids[-1]
                if dst in self.routers[src].shortest_paths:
                    self.routers[src].send_data(dst, "Test message after disconnect")
                else:
                    print(f"ПРЕДУПРЕЖДЕНИЕ: Нет пути от Router {src} до Router {dst} после разрыва")

        # Симулируем разрыв для кольцевой топологии
        if self.topology_type == "ring":
            # Берём два соседних роутера и разрываем соединение
            print("\n--- Имитация разрыва связи (соседние узлы) ---")
            nodes = sorted(self.routers.keys())
            r1 = nodes[0]
            r2 = nodes[1]
            self.designated_router.simulate_disconnect(r1, r2)
            time.sleep(2)
            print("\n--- Тестирование после разрыва ---")
            if len(nodes) >= 2:
                src = nodes[0]
                dst = nodes[-1]
                if dst in self.routers[src].shortest_paths:
                    self.routers[src].send_data(dst, "Test message after ring disconnect")
                else:
                    print(f"ПРЕДУПРЕЖДЕНИЕ: Нет пути от Router {src} до Router {dst} после разрыва кольца")

    def stop_simulation(self):
        for router in self.routers.values():
            router.stop()
        end_log = {
            "event_id": self.event_counter,
            "timestamp": datetime.now().isoformat(),
            "event_type": "SIMULATION_END",
            "simulation_id": self.simulation_id,
            "data": {}
        }
        self.event_counter += 1
        self._write_log(end_log)
        print("Сетевая симуляция остановлена")
    
    def print_statistics(self):
        print("\n=== СТАТИСТИКА СИМУЛЯЦИИ ===")
        print(f"Топология: {self.topology_type}")
        print(f"Количество маршрутизаторов: {len(self.routers) - 1}")
        print(f"Файл логов: {self.log_file}")
        print(f"Количество событий: {self.event_counter}")
        total_messages = 0
        for router_id, router in self.routers.items():
            print(f"Router {router_id}: {router.message_count} сообщений")
            total_messages += router.message_count
        print(f"Всего сообщений: {total_messages}")
        if self.designated_router:
            print(f"Изменений топологии: {self.designated_router.topology_changes}")

    
    def print_statistics(self):
        """Вывод статистики по симуляции"""
        print("\n=== СТАТИСТИКА СИМУЛЯЦИИ ===")
        print(f"Топология: {self.topology_type}")
        print(f"Количество маршрутизаторов: {len(self.routers) - 1}")
        print(f"Файл логов: {self.log_file}")
        print(f"Количество событий: {self.event_counter}")
        
        total_messages = 0
        for router_id, router in self.routers.items():
            print(f"Router {router_id}: {router.message_count} сообщений")
            total_messages += router.message_count
        
        print(f"Всего сообщений: {total_messages}")
        if self.designated_router:
            print(f"Изменений топологии: {self.designated_router.topology_changes}")

# Функция для интерактивного выбора топологии
def select_topology():
    print("Доступные топологии:")
    print("1. Линейная")
    print("2. Кольцо") 
    print("3. Звезда")
    
    choice = input("Выберите топологию (1-3): ").strip()
    
    if choice == "1":
        return "linear"
    elif choice == "2":
        return "ring"
    elif choice == "3":
        return "star"
    else:
        print("Неверный выбор, используется линейная топология по умолчанию")
        return "linear"

# Запуск симуляции
# В main части уменьшите общее время симуляции:
if __name__ == "__main__":
    print("=== СИМУЛЯТОР ПРОТОКОЛА OSPF ===")
    
    topology = select_topology()
    simulator = NetworkSimulator()
    
    if topology == "linear":
        simulator.create_linear_topology(5)
    elif topology == "ring":
        simulator.create_ring_topology(5)
    elif topology == "star":
        simulator.create_star_topology(5)
    
    try:
        simulator.start_simulation()
        time.sleep(10)  # Уменьшаем общее время симуляции
        simulator.print_statistics()
        
    except KeyboardInterrupt:
        print("\nСимуляция прервана пользователем")
    finally:
        simulator.stop_simulation()
