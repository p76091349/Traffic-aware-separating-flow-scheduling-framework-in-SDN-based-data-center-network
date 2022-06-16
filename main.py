from ryu import cfg
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import arp
from ryu.lib.packet import ipv4
from ryu.lib.packet import tcp
from ryu.lib.packet import udp

import network_awareness
import network_monitor
import setting
import random

#CONF = cfg.CONF


class ShortestForwarding(app_manager.RyuApp):
	"""
		ShortestForwarding is the class responsible for forwarding packets on shortest paths
		This class employs network_awareness and network_monitors functions to collect and discover
		network metrics and topology, respectively
	"""

	OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
	_CONTEXTS = {
		"network_awareness": network_awareness.NetworkAwareness,
		"network_monitor": network_monitor.NetworkMonitor}

	WEIGHT_MODEL = {'hop': 'weight', 'bw': 'bw'}

	def __init__(self, *args, **kwargs):
		super(ShortestForwarding, self).__init__(*args, **kwargs)
		self.name = "shortest_forwarding"
		self.awareness = kwargs["network_awareness"]
		self.monitor = kwargs["network_monitor"]
		self.datapaths = {}
		self.weight = 'bw'
		self.flwEntryCount = 0

	@set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
	def _state_change_handler(self, ev):
		"""
			Discover new and dead switches
		"""
		datapath = ev.datapath
		if ev.state == MAIN_DISPATCHER:
			if not datapath.id in self.datapaths:
				self.logger.debug('register datapath: %016x', datapath.id)
				self.datapaths[datapath.id] = datapath
		elif ev.state == DEAD_DISPATCHER:
			if datapath.id in self.datapaths:
				self.logger.debug('unregister datapath: %016x', datapath.id)
				del self.datapaths[datapath.id]

	@set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
	def _packet_in_handler(self, ev):
		"""
			OpenFlow packet_in handler. Using the APIs provoded by the controller, we can
			extract the L2, L3 and the payload of the arrived Packet-in. Then shortest_forwarding fuction is
			invoked to find the shortest paths
		"""
		msg = ev.msg
		pkt = packet.Packet(msg.data)
		arp_pkt = pkt.get_protocol(arp.arp)
		ip_pkt = pkt.get_protocol(ipv4.ipv4)
		
		if isinstance(arp_pkt, arp.arp):
			self.logger.debug("ARP processing")
			self.arp_forwarding(msg, arp_pkt.src_ip, arp_pkt.dst_ip)

		if isinstance(ip_pkt, ipv4.ipv4):
                        print('iperf packet-in')
			self.logger.debug("IPV4 processing")
			if len(pkt.get_protocols(ethernet.ethernet)):
				eth_type = pkt.get_protocols(ethernet.ethernet)[0].ethertype
				self.shortest_forwarding(msg, eth_type, ip_pkt.src, ip_pkt.dst)

	def add_flow(self, dp, priority, match, actions, idle_timeout=0, hard_timeout=0):
		"""
			adding new flow entry to the switch indicated in dp by using OPF_Flow_MOD message
		"""
		ofproto = dp.ofproto
		parser = dp.ofproto_parser
		inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
		mod = parser.OFPFlowMod(datapath=dp, priority=priority,
								idle_timeout=idle_timeout,
								hard_timeout=hard_timeout,
								match=match, instructions=inst)
		dp.send_msg(mod)

	def _build_packet_out(self, datapath, buffer_id, src_port, dst_port, data):
		"""
			Build packet-out message which is ofp_packet_out to be sent to the switch which sent packet-in message
			indicating the buffer_id in case it is existed
		"""
		actions = []
		if dst_port:
			actions.append(datapath.ofproto_parser.OFPActionOutput(dst_port))

		msg_data = None
		if buffer_id == datapath.ofproto.OFP_NO_BUFFER:
			if data is None:
				return None
			msg_data = data

		out = datapath.ofproto_parser.OFPPacketOut(
			datapath=datapath, buffer_id=buffer_id,
			data=msg_data, in_port=src_port, actions=actions)
		return out

	def send_packet_out(self, datapath, buffer_id, src_port, dst_port, data):
		"""
			Send packet-out message to the datapath.
		"""
		out = self._build_packet_out(datapath, buffer_id,
									 src_port, dst_port, data)
		if out:
			datapath.send_msg(out)

	def get_port_pair_from_link(self, link_to_port, src_dpid, dst_dpid):
		"""
			Get information of two link ends, so that controller can install flow entry.
			where link_to_port = {(src_dpid,dst_dpid):(src_port,dst_port),} is a dictionary
			created by network.awareness module
		"""
		if (src_dpid, dst_dpid) in link_to_port:
			return link_to_port[(src_dpid, dst_dpid)]
		else:
			self.logger.info("Link from dpid:%s to dpid:%s is not in links" %
			 (src_dpid, dst_dpid))
			return None

	def flood(self, msg):
		"""
			Flood packet to the access ports which have no record of host.
			access_ports = {dpid:set(port_num,),}
			access_table = {(sw,port):(ip, mac),}
		"""
		datapath = msg.datapath
		ofproto = datapath.ofproto

		for dpid in self.awareness.access_ports:
			for port in self.awareness.access_ports[dpid]:
				if (dpid, port) not in self.awareness.access_table.keys():
					datapath = self.datapaths[dpid]
					out = self._build_packet_out(
						datapath, ofproto.OFP_NO_BUFFER,
						ofproto.OFPP_CONTROLLER, port, msg.data)
					datapath.send_msg(out)
		self.logger.debug("Flooding packet to access port")

	def arp_forwarding(self, msg, src_ip, dst_ip):
		"""
			Send ARP packet to the destination host if the dst host record
			is existed, else flow it to the unknow access port.
			result = (datapath, port)
		"""
		datapath = msg.datapath
		ofproto = datapath.ofproto

		result = self.awareness.get_host_location(dst_ip)
		if result:
			# Host has been recorded in access table.
			datapath_dst, out_port = result[0], result[1]
			datapath = self.datapaths[datapath_dst]
			out = self._build_packet_out(datapath, ofproto.OFP_NO_BUFFER,
										 ofproto.OFPP_CONTROLLER,
										 out_port, msg.data)
			datapath.send_msg(out)
			self.logger.debug("Deliver ARP packet to knew host")
		else:
			# Flood is not good.
			self.flood(msg)

	def get_path(self, src, dst, weight):
		"""
			get the shortest paths between src and dst either based on hop counts
			using the networkx generator, where the network topology is represented as a
			graph or based on the available BW on links.
			we choice 2 shortest paths between a src and dst then chooses the one
			has the max available BW. 
		"""
		shortest_paths = self.awareness.shortest_paths
		# Create bandwidth-sensitive datapath graph.
		graph = self.awareness.graph

		
		if weight == 'bw':
			""" Because all paths will be calculated when we call self.monitor.get_best_path_by_bw,
			 so we just need to call it once in a period, and then, we can get path directly.
			 If path is existed just return it, else calculate and return it."""
			try:
                                path = self.monitor.best_paths.get(src).get(dst)
                                
                                
                            
                                        

                                return path
			except:
				result = self.monitor.get_best_path_by_bw(graph, shortest_paths)    #get_best_path_by_portbw(dpid,graph,path,speed)
				paths = result[1]
				best_path = paths.get(src).get(dst)
                                
                        
                                return best_path
		else:
			pass
       
	def get_sw(self, dpid, in_port, src, dst):
		"""
			find the src and dst switches because Sieves computes the shortest paths
			between src dpid and dst dpid not between src ip and dst ip since the graph
			represents the network topology layers only: access, aggregate and core
		"""
		src_sw = dpid
		dst_sw = None
		src_location = self.awareness.get_host_location(src)   # src_location = (dpid, port)
		if in_port in self.awareness.access_ports[dpid]:
			if (dpid, in_port) == src_location:
				src_sw = src_location[0]
			else:
				src_sw = dpid
				#return None
		dst_location = self.awareness.get_host_location(dst)   # dst_location = (dpid, port)
		if dst_location:
			dst_sw = dst_location[0]
		if src_sw and dst_sw:
			return src_sw, dst_sw
		else:
			return None

	def send_flow_mod(self, datapath, flow_info, src_port, dst_port):
		"""
			Build flow entry, and send it to datapath. Sieve uses 
			flow_info = (eth_type, src_ip, dst_ip, in_port, ip_proto, Flag, L4_port) which is 
			ofp_match is used to identify each flow uniquely. Besides, Sieve can deal with UDP flows.
			action here is outport applied on match flows.
			We set 30 as priority of the flows installed by this module with idle_timeout = 5 sec
		"""
		parser = datapath.ofproto_parser
		actions = []
		actions.append(parser.OFPActionOutput(dst_port))
		if len(flow_info) == 9:
			#print("IT IS 9 FEILDS")
			if flow_info[-5] == 6:
				if flow_info[-4] == 'src':
					if flow_info[-2] == 'dst':
						match = parser.OFPMatch(
							in_port=src_port, eth_type=flow_info[0],
							ipv4_src=flow_info[1], ipv4_dst=flow_info[2],
							ip_proto=6, tcp_src=flow_info[-3], tcp_dst=flow_info[-1])
				else:
					pass
                        
                        
                        if flow_info[-5] == 6:
                                if flow_info[-4] == 'src':
                                        if flow_info[-2] == 'dst':
                                                match = parser.OFPMatch(
                                                        in_port=src_port, eth_type=flow_info[0],
                                                        ipv4_src=flow_info[1], ipv4_dst=flow_info[2],
                                                        ip_proto=6, tcp_dst=flow_info[-1])

			elif flow_info[-5] == 17:
				if flow_info[-4] == 'src':
					if flow_info[-2] == 'dst':
						match = parser.OFPMatch(
							in_port=src_port, eth_type=flow_info[0],
							ipv4_src=flow_info[1], ipv4_dst=flow_info[2],
							ip_proto=17, udp_src=flow_info[-3], udp_dst=flow_info[-1])
				else:
					pass
		elif len(flow_info) == 4:
			match = parser.OFPMatch(
						in_port=src_port, eth_type=flow_info[0],
						ipv4_src=flow_info[1], ipv4_dst=flow_info[2])
		else:
			pass
		#if we need to modify the timeout so we can do it here

                self.add_flow(datapath, priority, match, actions,
					  idle_timeout=10, hard_timeout=0)

	def install_flow(self, datapaths, link_to_port, path, flow_info, buffer_id, data=None):
		"""
			Install flow entries into the datapaths of the chosen path (shortest path with
			max BW) in path=[dpid1, dpid2, ...]
			flow_info = (eth_type, src_ip, dst_ip, in_port) or
			flow_info = (eth_type, ip_src, ip_dst, in_port, ip_proto, sFlag, L4_sport, dFlag, L4_dport)
			in case of Sieve, it is 9 fields for flow matching. flow installation starts with the intermediate datapaths
			then the first datapath to make sure that all datapaths along the path know how to forward packets otherwise
			the packets will be sent to Sieve many time and overwhelm it.
		"""
		if path is None or len(path) == 0:
			self.logger.info("Path error!")
			return
		# the port at which the packet arrived
		in_port = flow_info[3]
		# the switch at which the packet arrived
		first_dp = datapaths[path[0]]
		# local virtual port on first switch
		out_port = first_dp.ofproto.OFPP_LOCAL
                if len(flow_info) == 9:
			flow_key = (flow_info[1],flow_info[2],flow_info[6],flow_info[8])
		else:
			flow_key = (flow_info[1],flow_info[2])
		# count the number of flows scheduled by this module
		self.flwEntryCount += 1
		# Install flow entry for intermediate datapaths.
		for i in xrange(1, len(path) - 1):
			port = self.get_port_pair_from_link(link_to_port, path[i-1], path[i])
			port_next = self.get_port_pair_from_link(link_to_port, path[i], path[i+1])
			if port and port_next:
				src_port, dst_port = port[1], port_next[0]
				datapath = datapaths[path[i]]
				self.send_flow_mod(datapath, flow_info, src_port, dst_port)
		#  Install flow entry for the first datapath.
		port_pair = self.get_port_pair_from_link(link_to_port, path[0], path[1])
		if port_pair is None:
			self.logger.info("Port not found in first hop.")
			return
		# the out port on the first datapath, this port will be used as outport in the action command
		out_port = port_pair[0]
		self.send_flow_mod(first_dp, flow_info, in_port, out_port)
		# Send packet_out to the first datapath.
		self.send_packet_out(first_dp, buffer_id, in_port, out_port, data)

	def get_L4_info(self, tcp_pkt, udp_pkt):
		"""
			Using the APIs provided by RYU controller, we can get L4 
			information in case of TCP and UDP flows to be used for
			the remaining functions.
		"""
		ip_proto = None
		L4_sport = None
		sFlag = None
		L4_dport = None
		dFlag = None
		if tcp_pkt:
			ip_proto = 6
			if tcp_pkt.src_port:
				L4_sport = tcp_pkt.src_port
				sFlag = 'src'
			if tcp_pkt.dst_port:
				L4_dport = tcp_pkt.dst_port
				dFlag = 'dst'
			else:
				pass
		elif udp_pkt:
			ip_proto = 17
			if udp_pkt.src_port:
				L4_sport = udp_pkt.src_port
				sFlag = 'src'
			if udp_pkt.dst_port:
				L4_dport = udp_pkt.dst_port
				dFlag = 'dst'
			else:
				pass
		else:
			pass
		return (ip_proto, L4_sport, sFlag, L4_dport, dFlag)

	def shortest_forwarding(self, msg, eth_type, ip_src, ip_dst):
		"""
			This the function is invoked when receive a new packet-in msg
			and it invokes the previous functions untill install new flow
			entries.
		"""
		datapath = msg.datapath
		in_port = msg.match['in_port']
		pkt = packet.Packet(msg.data)
		tcp_pkt = pkt.get_protocol(tcp.tcp)
		udp_pkt = pkt.get_protocol(udp.udp)
		ip_proto = None
		L4_port = None
		Flag = None
		# Get ip_proto and L4 port number.
		ip_proto, L4_sport, sFlag, L4_dport, dFlag = self.get_L4_info(tcp_pkt, udp_pkt)
		result = self.get_sw(datapath.id, in_port, ip_src, ip_dst)   # result = (src_sw, dst_sw)
		if result:
			src_sw, dst_sw = result[0], result[1]
			if dst_sw:
				# Path has already been calculated, just get it.
				path = self.get_path(src_sw, dst_sw, weight=self.weight)
                            
				#print "path for packet-in:", path
				if ip_proto and dFlag and sFlag:
					if ip_proto == 6:
						L4_Proto = 'TCP'
					elif ip_proto == 17:
						L4_Proto = 'UDP'
					else:
						pass
					#self.logger.info("[PATH]%s<-->%s(%s Port:%d): %s" % (ip_src, ip_dst, L4_Proto, L4_port, path))
					flow_info = (eth_type, ip_src, ip_dst, in_port, ip_proto, sFlag, L4_sport, dFlag, L4_dport)
				else:
					#self.logger.info("[PATH]%s<-->%s: %s" % (ip_src, ip_dst, path))
					flow_info = (eth_type, ip_src, ip_dst, in_port)
				# Install flow entries to datapaths along the path.
				self.install_flow(self.datapaths,
								  self.awareness.link_to_port,
								  path, flow_info, msg.buffer_id, msg.data)
		else:
			# Flood the packet out of the remaining ports in case we can not get information of src, dst datapath
			self.flood(msg)
