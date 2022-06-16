# Copyright (C) 2021 Maiass Zaher at Budapest University 
# of Technology and Economics, Budapest, Hungary.
# Copyright (C) 2016 Li Cheng at Beijing University of Posts
# and Telecommunications.
# Copyright (C) 2016 Huang MaChi at Chongqing University
# of Posts and Telecommunications, China.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
This module represents the third layer of Sieve. It is responsible for
elephant (large) flow reseduling, detection and port monitoring
"""

from __future__ import division
import copy
from operator import attrgetter

from ryu import cfg
from ryu.base import app_manager
from ryu.base.app_manager import lookup_service_brick
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub
import logging
import setting
import time

CONF = cfg.CONF

class NetworkMonitor(app_manager.RyuApp):
	"""
		NetworkMonitor is the class responsible for collecting traffic metrics and rescheduling elephant flows.
	"""
	OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

	def __init__(self, *args, **kwargs):
		super(NetworkMonitor, self).__init__(*args, **kwargs)
		self.name = 'monitor'
		self.datapaths = {}
		self.port_speed = {}
		self.flow_speed = {}
                self.port_stats = {}
		self.stats = {}
		self.port_features = {}
		self.free_bandwidth = {}   # self.free_bandwidth = {dpid:{port_no:free_bw,},} unit:Kbit/s
		self.awareness = lookup_service_brick('awareness')
		self.graph = None
		self.capabilities = None
		self.best_paths = None
		self.edgdps = [3001,3002,3003,3004,3005,3006,3007,3008]
		self.aggdps = [2001,2002,2003,2004,2005,2006,2007,2008]
		self.cordps = [1001,1002,1003,1004]
		self.sw_out_inf = {}
		self.redir_flowcounter = 100
		self.redir_flow_num = 0
		self.port_capacity = {3:{1:20000, 2:20000, 3:10000, 4:10000}, 2:{1:100000, 2:100000, 3:20000, 4:20000}}
		self.path = None
		self.flow_info = None
		self.path_redir_flows = None
		self.fsCount = 0
		self.failCount = 0
		self.totalCount = 0
		self.flwEntryCount = 0
                self.r_times=[]
		# Start green thread to monitor traffic and calculating
		# free bandwidth of links, respectively.
		self.monitor_thread = hub.spawn(self._monitor)
		self.save_freebandwidth_thread = hub.spawn(self._save_bw_graph)
                self.s=time.time()

	def _monitor(self):
		"""
			Send requests for collecting network statistics
		"""
	#	while CONF.weight == 'bw':
                while True:
                #self.sw_out_inf = {}
                    #print("_monitor")
	    	    self.stats['flow'] = {}
	    	    self.stats['port'] = {}
		    for dp in self.datapaths.values():
		        self.port_features.setdefault(dp.id, {})
	    	        self._request_stats(dp)
    		        # Refresh data.				
                        self.capabilities = None
		        self.best_paths = None
                    print('r times',sum(self.r_times))
		    hub.sleep(setting.MONITOR_PERIOD)
	def _save_bw_graph(self):
		"""
			Save BW values into networkx graph.
		"""
	#	while CONF.weight == 'bw':
                while True:
		    self.graph = self.create_bw_graph(self.free_bandwidth)
		    self.logger.debug("save free bandwidth")
                    #print('flow sleep ',setting.MONITOR_PERIOD)
		    hub.sleep(setting.MONITOR_PERIOD)

	@set_ev_cls(ofp_event.EventOFPStateChange,
				[MAIN_DISPATCHER, DEAD_DISPATCHER])
	def _state_change_handler(self, ev):
		"""
			Add or remove datapaths
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
		else:
			pass

	@set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
	def _flow_stats_reply_handler(self, ev):
		"""
			handler of flow statistics message replies from datapathes
			Because the proactive flow entrys don't have 'in_port' and 'out-port' field.
			Note: table-miss, LLDP and ARP flow entries are not what we need, just filter them.
		"""
		body = ev.msg.body
		dpid = ev.msg.datapath.id
		self.stats['flow'][dpid] = body
		self.flow_speed.setdefault(dpid, {})
		# excluding the proactive flow entries
		if dpid in self.edgdps:
			flow_num = len(body) - 6
		elif dpid in self.cordps:
			flow_num = len(body) - 18
		elif dpid in self.aggdps:
			flow_num = len(body) - 6
		paths = []
                m_paths = []
		flow_port = {}
		self.path = None
		self.flow_info = None
		self.path_redir_flows = {}
		if flow_num > 0:
			key1 = None
                        key2 = None
                        
                        #for stat in sorted([flow for flow in body if ((flow.priority not in [0, 1000, 10, 65535]) and (flow.instructions[0].actions[0].port == self.sw_out_inf[dpid]) and (flow.byte_count < 15) and flow.match.get('tcp_src'))],
                        #                                   key=lambda flow: (flow.priority, flow.match.get('ipv4_src'), flow.match.get('ipv4_dst'))):
                        #        key1 = (dpid, stat.instructions[0].actions[0].port,stat.byte_count)
                        #        m_paths.append([stat.match.get('eth_type'), stat.match.get('in_port'), stat.match.get('ipv4_src'), stat.match.get('ipv4_dst'), stat.match.get('tcp_src'), stat.match.get('tcp_dst'), stat.priority])
                        #        print([stat.match.get('ipv4_src'), stat.match.get('ipv4_dst'), stat.priority])
                        #        print('m_paths',m_paths)

			# elephant flows detection egressing out a specific port by considering just elephant flows whose size above 50 KB, TCP flows, and egress out the port specified in sw_out_inf
                        
                       # for stat in sorted([flow for flow in body ],
		       # 				   key=lambda flow: (flow.priority, flow.match.get('ipv4_src'), flow.match.get('ipv4_dst'))):
		       # 	key2 = (dpid, stat.instructions[0].actions[0].port,stat.byte_count)
                       #         #print('key1',key1)
                       #         print('key2',key2)
                       #         print('actions',stat.instructions[0].actions[0])
		       # 	# creating a list of the detected elephant flows
                       #         
		       # 	paths.append([stat.match.get('eth_type'), stat.match.get('in_port'), stat.match.get('ipv4_src'), stat.match.get('ipv4_dst'), stat.match.get('tcp_src'), stat.match.get('tcp_dst'), stat.priority])
                       #         print([stat.match.get('ipv4_src'), stat.match.get('ipv4_dst'), stat.priority])
 

			for stat in sorted([flow for flow in body if ((flow.priority not in [0, 1000, 10, 65535]) and (flow.instructions[0].actions[0].port == self.sw_out_inf[dpid]) and flow.byte_count > 50 and flow.match.get('tcp_src'))],
							   key=lambda flow: (flow.priority, flow.match.get('ipv4_src'), flow.match.get('ipv4_dst'))):
				key2 = (dpid, stat.instructions[0].actions[0].port,stat.byte_count)
				# creating a list of the detected elephant flows
                                
				paths.append([stat.match.get('eth_type'), stat.match.get('in_port'), stat.match.get('ipv4_src'), stat.match.get('ipv4_dst'), stat.match.get('tcp_src'), stat.match.get('tcp_dst'), stat.priority])
                                for i in range(0,len(key2)):
                                        self.get_path_by_fqouta(dpid, flow_port[key2][i][1], 2048, flow_port[key2][i][2], flow_port[key2][i][3], flow_port[key2][i][4], flow_port[key2][i][5], 30, key2[1], self.free_bandwidth[dpid][self.sw_out_inf[dpid]], self.redir_flow_num)
	

                           
                        
			if key2 and key1 == None:
				flow_port[key2] = paths
				port_flow_num = len(flow_port[key2])
				if dpid > 3000:
					capacity = self.port_capacity[3][stat.instructions[0].actions[0].port]  #capacity 10000
                                        load_thre = 0.35
				elif dpid > 2000:
					capacity = self.port_capacity[2][stat.instructions[0].actions[0].port]  #capacity 20000
                                        if stat.instructions[0].actions[0].port in (1,2):
						load_thre = 0.35
					else:
						load_thre = 0.35
				else:
					capacity = 100000
					load_thre = 0.35
				# compute the occupied BW on a specific port
				load_current_port = round((1 - (self.free_bandwidth[dpid][self.sw_out_inf[dpid]]/capacity)),1)
				# compute the total number of elephant flows must be rescheduled based on the BW occupation and the number of elephant flows
				if int(load_current_port) == 1:
					self.redir_flow_num = int(port_flow_num/2)
				elif port_flow_num == 1:
					self.redir_flow_num = 1	
				else:
					self.redir_flow_num = int(port_flow_num*load_current_port)
			        #print('dpid, current load, capacity, load thre',dpid,load_current_port,capacity,load_thre)	
				print "we should redirect the followig number of flows:", self.redir_flow_num
                                if self.redir_flow_num != 0:
                                        self.r_times.append(1)
				self.totalCount += self.redir_flow_num
				# looking for other paths for the detected elephant flows so that the current port is not a part of the new paths

                                #self.redir_flow_num = 0
				if self.redir_flow_num > 0 and load_current_port >= 0.45:
					for i in range(0,self.redir_flow_num):
						self.get_path_by_fqouta(dpid, flow_port[key2][i][1], 2048, flow_port[key2][i][2], flow_port[key2][i][3], flow_port[key2][i][4], flow_port[key2][i][5], 30, key2[1], self.free_bandwidth[dpid][self.sw_out_inf[dpid]], self.redir_flow_num)
				else:
					print "Either no flows should be redirected or the load is below the threshold"
                                
		else:
			print "No flow_num <= 0"
			

	@set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
	def _port_stats_reply_handler(self, ev):
		"""
			handle port's statitic and save it in port_speed dictionary.
			self.port_speed = {(dpid, port_no):[speed,],}
			Note: The transmit performance and receive performance are independent of a port.
			We calculate the load of a port only using tx_bytes.
		"""
                all_load=0
		body = ev.msg.body
		dpid = ev.msg.datapath.id
		self.stats['port'][dpid] = body
		self.free_bandwidth.setdefault(dpid, {})
                l={}
                load=[]
		for stat in sorted(body, key=attrgetter('port_no')):
			port_no = stat.port_no
			if port_no != ofproto_v1_3.OFPP_LOCAL:
				key = (dpid, port_no)
				value = (stat.tx_bytes, stat.rx_bytes, stat.rx_errors,
						 stat.duration_sec, stat.duration_nsec)
				self._save_stats(self.port_stats, key, value, 5)

				# Get port speed and Save it.
				pre = 0
				period = setting.MONITOR_PERIOD
				tmp = self.port_stats[key]
				if len(tmp) > 1:
					# Calculate only the tx_bytes, not the rx_bytes. (hmc)
					pre = tmp[-2][0]
					period = self._get_period(tmp[-1][3], tmp[-1][4], tmp[-2][3], tmp[-2][4])
				speed = self._get_speed(self.port_stats[key][-1][0], pre, period)
                                #print('dpid, port no, speed',dpid,port_no,speed)
				self._save_stats(self.port_speed, key, speed, 5)
				self._save_freebandwidth(dpid, port_no, speed)
                        #if dpid > 3000 and port_no in (1,2):
                        #        l.append((20000 - self.free_bandwidth[dpid][port_no]) / 20000)
                        #        all_load = all_load + (20000 - self.free_bandwidth[dpid][port_no]) / 20000
                        #        print('dpid,port,load,free bw`:',dpid, port_no, round((20000 - self.free_bandwidth[dpid][port_no]) / 20000,2),self.free_bandwidth[dpid][port_no])
                        #        print('all load',all_load)
                        #        print('list len',len(l))
                        #        print('list',l)
                for i in xrange(3001,3009):
                    if i in self.free_bandwidth:    
                        l.setdefault(i,{})
                        l[i][1]=round((20000 - self.free_bandwidth[i][1]) / 20000,3)
                        l[i][2]=round((20000 - self.free_bandwidth[i][2]) / 20000,3)
                        load.append(l[i][1])
                        load.append(l[i][2])
                if sum(load)/16 < 0.25:
                    setting.MONITOR_PERIOD=10**round((0.25-sum(load)/16)/0.25,2)
                else:
                    setting.MONITOR_PERIOD=2
	@set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
	def port_desc_stats_reply_handler(self, ev):
		"""
			Save port description info.
		"""
		msg = ev.msg
		dpid = msg.datapath.id
		ofproto = msg.datapath.ofproto

		config_dict = {ofproto.OFPPC_PORT_DOWN: "Down",
					   ofproto.OFPPC_NO_RECV: "No Recv",
					   ofproto.OFPPC_NO_FWD: "No Farward",
					   ofproto.OFPPC_NO_PACKET_IN: "No Packet-in"}

		state_dict = {ofproto.OFPPS_LINK_DOWN: "Down",
					  ofproto.OFPPS_BLOCKED: "Blocked",
					  ofproto.OFPPS_LIVE: "Live"}

		ports = []
		for p in ev.msg.body:
			ports.append('port_no=%d hw_addr=%s name=%s config=0x%08x '
						 'state=0x%08x curr=0x%08x advertised=0x%08x '
						 'supported=0x%08x peer=0x%08x curr_speed=%d '
						 'max_speed=%d' %
						 (p.port_no, p.hw_addr,
						  p.name, p.config,
						  p.state, p.curr, p.advertised,
						  p.supported, p.peer, p.curr_speed,
						  p.max_speed))

			if p.config in config_dict:
				config = config_dict[p.config]
			else:
				config = "up"

			if p.state in state_dict:
				state = state_dict[p.state]
			else:
				state = "up"

			# Recording data.
			port_feature = (config, state, p.curr_speed)
			self.port_features[dpid][p.port_no] = port_feature

	@set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
	def _port_status_handler(self, ev):
		"""
			Handle the port status changed event.
		"""
		msg = ev.msg
		ofproto = msg.datapath.ofproto
		reason = msg.reason
		dpid = msg.datapath.id
		port_no = msg.desc.port_no

		reason_dict = {ofproto.OFPPR_ADD: "added",
					   ofproto.OFPPR_DELETE: "deleted",
					   ofproto.OFPPR_MODIFY: "modified", }

		if reason in reason_dict:
			print "switch%d: port %s %s" % (dpid, reason_dict[reason], port_no)
		else:
			print "switch%d: Illeagal port state %s %s" % (dpid, port_no, reason)

	def _request_stats(self, datapath):
		"""
			Sending OFP_PORT_DESCRIPTION and OFP_PORT_STATS requests to all datapaths
		"""
		self.logger.debug('send stats request: %016x', datapath.id)
		ofproto = datapath.ofproto
		parser = datapath.ofproto_parser
		req = parser.OFPPortDescStatsRequest(datapath, 0)
		datapath.send_msg(req)
		req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
		datapath.send_msg(req)
	
	def get_sw(self, dpid, in_port, src, dst):
		"""
			Get pair of source and destination switches.
		"""
		try:
			src_sw = dpid
			dst_sw = None
			if src_sw:
				dst_location = self.awareness.get_host_location(dst)   # dst_location = (dpid, port)
				if dst_location:
					dst_sw = dst_location[0]
				if src_sw and dst_sw:
					return src_sw, dst_sw
				else:
					return None
					print "we couldn't find either the source or the destunation"
			else:
				print "no src sw"
				return None
		except KeyError:
			traceback.print_exc()
	
	def get_min_bw_of_ports(self, graph, path, min_bw):
		"""
			Getting bandwidth of path. Actually, the mininum bandwidth
			of links is the path's bandwith, because it is the bottleneck of path.
		"""
		_len = len(path)
		if _len > 1:
			minimal_band_width = min_bw
			for i in xrange(_len-1):
				pre, curr = path[i], path[i+1]
				if 'bandwidth' in graph[pre][curr]:
					bw = graph[pre][curr]['bandwidth']
					minimal_band_width = min(bw, minimal_band_width)
					if bw < minimal_band_width:
						pre, curr = path[i], path[i+1]
				else:
					#print "not in the graph"
					continue
			return minimal_band_width, pre, curr
		else:
			return min_bw

	def get_best_path_by_portbw(self, dpid, graph, paths, speed):
		"""
			Get best path by comparing the available paths. The best one
			will be the one whose bottleneck link has available BW more than that on
			the under-threshold port.
		"""
		best_paths = copy.deepcopy(paths)
                print('best_paths',best_paths)
		max_bw_of_paths = speed
		best_path = {}
		pre = 1
		curr = 1
		for path in paths:
			min_bw = 100000
			max_bw = 0
			min_bw, pre1, curr1 = self.get_min_bw_of_ports(graph, path, min_bw)
                        if min_bw > max_bw_of_paths and int(min_bw - speed) > 500: #and min_bw-(1-speed)>speed:
				max_bw_of_paths = min_bw
				best_path = path
				pre, curr = pre1, curr1
		if len(best_path) > 0 and pre > 0 and curr > 0:
                    print('reschedule path',best_path)
                    logging.debug('reschedule path',best_path)
		    return best_path, pre, curr
		else:
			return {}, 0, 0
        
        def get_best_path_by_bw(self,graph,paths):
            capabilities={}
            best_paths=copy.deepcopy(paths)
            
            for src in paths:
                for dst in paths[src]:
                    if src == dst:
                        best_paths[src][src]=[src]
                        capabilities.setdefault(src,{src: 10000})
                        capabilities[src][src]=10000
                    else:
                        max_bw_of_paths=0
                        best_path=paths[src][dst][0]
                        for path in paths[src][dst]:
                            min_bw=10000
                            min_bw=self.get_min_bw_of_ports(graph , path , min_bw)
                            if min_bw > max_bw_of_paths:
                                max_bw_of_paths = min_bw
                                best_path = path
                        best_paths[src][dst] = best_path
                        capabilities.setdefault(src,{dst:max_bw_of_paths})
                        capabilities[src][dst] = max_bw_of_paths
            self.capabilities = capabilities
            self.best_paths = best_paths
            return capabilities,best_paths

	def get_port_pair_from_link(self, link_to_port, src_dpid, dst_dpid):

		if (src_dpid, dst_dpid) in link_to_port:
			return link_to_port[(src_dpid, dst_dpid)]
		else:
			self.logger.info("Link from dpid:%s to dpid:%s is not in links" %
			 (src_dpid, dst_dpid))
			return None
			
	def get_path(self, dpid, outgoing_inf, src, dst, weight, speed):
		"""
			Finding the shortest paths for the rescheduled elephant flow, then
			invoke get_best_path_by_portbw to find the suitable one.
		"""
		shortest_paths = self.awareness.shortest_paths
		graph = self.awareness.graph
		best_path = {}
		paths = []
		pre = 0
		curr = 0
		for path in shortest_paths.get(src).get(dst):
			port_pair = self.get_port_pair_from_link(self.awareness.link_to_port, path[0], path[1])
			if port_pair[0] != outgoing_inf:
				paths.append(path)
		best_path, pre, curr = self.get_best_path_by_portbw(dpid, graph, paths, speed)
		if len(best_path) > 0 and pre > 0 and curr > 0:
			return best_path, pre, curr
		else:
			return {}, 0, 0
	
	def add_flow(self, dp, priority, match, actions, hard_timeout):
		ofproto = dp.ofproto
		parser = dp.ofproto_parser
		inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
		mod = parser.OFPFlowMod(datapath=dp, priority=priority,
								hard_timeout=hard_timeout,
								match=match, instructions=inst)
		dp.send_msg(mod)

	def send_flow_mod(self, datapath, flow_info, src_port, dst_port):
		""" 
			install new flow entries for the rescheduled elephant flows
			so that their priority is higher than the existed ones.
		"""
		parser = datapath.ofproto_parser
		actions = []
		actions.append(parser.OFPActionOutput(dst_port))
		if len(flow_info) == 8:
			match = parser.OFPMatch(
				in_port=src_port, eth_type=flow_info[0],
				ipv4_src=flow_info[1], ipv4_dst=flow_info[2],
				ip_proto=6, tcp_src=flow_info[-3], tcp_dst=flow_info[-2])
		elif len(flow_info) == 4:
			match = parser.OFPMatch(
						in_port=src_port, eth_type=flow_info[0],
						ipv4_src=flow_info[1], ipv4_dst=flow_info[2])
		#if we need to modify the timeout so we can do it here
		priority = flow_info[-1] + 1
		self.add_flow(datapath, priority, match, actions,
					  hard_timeout=6)
		
	def install_flow(self, datapaths, link_to_port, path, flow_info):
		
                
		if path is None or len(path) == 0:
			print "Path error is zero length!"
			self.logger.info("Path error!")
			return
		in_port = flow_info[3]
		first_dp = datapaths[path[0]]
		out_port = first_dp.ofproto.OFPP_LOCAL
		self.flwEntryCount += 1
		# Install flow entry for intermediate datapaths.
		for i in xrange(1, len(path) - 1):
			port = self.get_port_pair_from_link(link_to_port, path[i-1], path[i])
			port_next = self.get_port_pair_from_link(link_to_port, path[i], path[i+1])
			if port and port_next:
				src_port, dst_port = port[1], port_next[0]
				datapath = datapaths[path[i]]
				self.send_flow_mod(datapath, flow_info, src_port, dst_port)
			else:
				print "we couldn't find the port pais for the intermediate dp"
		
		#  Install flow entry for the first datapath.
		port_pair = self.get_port_pair_from_link(link_to_port, path[0], path[1])
		if port_pair is None:
			print "we couldn't find the port_pair of the first dp"
			self.logger.info("Port not found in first hop.")
			return
		out_port = port_pair[0]
		self.send_flow_mod(first_dp, flow_info, in_port, out_port)
	
	def get_path_by_fqouta(self, dpid, in_port, eth_type, ip_src, ip_dst, L4_sport, L4_dport, priority, outgoing_inf, speed, flownumber):
		"""
			Get the src and dst datapahs info, try to find the suitable path. Then, install the flow entries
			into datapaths along the chosen path.
		"""
		result = self.get_sw(dpid, in_port, ip_src, ip_dst)   
		if result:
			src_sw, dst_sw = result[0], result[1]
			if dst_sw:
				# Path has already been calculated, just get it.
				
				path, pre, curr = self.get_path(dpid, outgoing_inf, src_sw, dst_sw, 'fnum', speed)
				if len(path) > 0:
					graph = self.awareness.graph
					flow_info = (eth_type, ip_src, ip_dst, in_port, 6, L4_sport, L4_dport, priority)
					self.install_flow(self.datapaths,
								  self.awareness.link_to_port,
								  path, flow_info)
				else:
					self.failCount += 1
					print "No path found at all under the specified conditions"
		else:
			print "src_sw, dst_sw couldn't be found"
			
	
	def create_bw_graph(self, bw_dict):
		"""
			Save bandwidth data into networkx graph object.
		"""
		try:
			graph = self.awareness.graph
			link_to_port = self.awareness.link_to_port
			for link in link_to_port:
				(src_dpid, dst_dpid) = link
				(src_port, dst_port) = link_to_port[link]
				if src_dpid in bw_dict and dst_dpid in bw_dict:
					bw_src = bw_dict[src_dpid][src_port]
					bw_dst = bw_dict[dst_dpid][dst_port]
					bandwidth = min(bw_src, bw_dst)
					# Add key:value pair of bandwidth into graph.
					if graph.has_edge(src_dpid, dst_dpid):
						graph[src_dpid][dst_dpid]['bandwidth'] = bandwidth
					else:
						graph.add_edge(src_dpid, dst_dpid)
						graph[src_dpid][dst_dpid]['bandwidth'] = bandwidth
				else:
					if graph.has_edge(src_dpid, dst_dpid):
						graph[src_dpid][dst_dpid]['bandwidth'] = 0
					else:
						graph.add_edge(src_dpid, dst_dpid)
						graph[src_dpid][dst_dpid]['bandwidth'] = 0
			return graph
		except:
			self.logger.info("Create bw graph exception")
			if self.awareness is None:
				self.awareness = lookup_service_brick('awareness')
			return self.awareness.graph

	def _save_freebandwidth(self, dpid, port_no, speed):
		"""
			Calculate free bandwidth of port and Save it.
			port_feature = (config, state, p.curr_speed)
			self.port_features[dpid][p.port_no] = port_feature
			self.free_bandwidth = {dpid:{port_no:free_bw,},}
			We compute the free BW based on the difference between
			link capacity and the current speed.
			in case the free bandwidth is below the predefined threshold,
			then send OFP_FLOW_Stats request to poll all flow information
			on port_no
		"""
		self.free_bandwidth.setdefault(dpid, {})
		port_state = self.port_features.get(dpid).get(port_no)
		if port_state:
			
			if dpid > 3000:
				#capacity = self.port_capacity[3][port_no]
                                capacity = 20000


			elif dpid > 2000:
				#capacity = self.port_capacity[2][port_no]
                                capacity = 20000

			else:
				#capacity = 100000
                                capacity = 20000

			
			free_bw = self._get_free_bw(capacity, speed)
			self.free_bandwidth[dpid].setdefault(port_no, 0)
			self.free_bandwidth[dpid][port_no] = free_bw
                        #print('dpid, port no, free bw', dpid, port_no, self.free_bandwidth[dpid][port_no]) 
                       # all_load=0
                       # if dpid > 3000 and port_no in (1,2):
                       #     l.append((capacity - self.free_bandwidth[dpid][port_no]) / capacity)
                       #     all_load = all_load + (capacity - self.free_bandwidth[dpid][port_no]) / capacity
                       #     print('dpid,port,load',dpid, port_no, (capacity - self.free_bandwidth[dpid][port_no]) / capacity)
                       #     print('all load',all_load)
                       #     print(
			if dpid in self.edgdps and port_no in [1,2]:
				if free_bw < 15000:
					self.sw_out_inf[dpid] = port_no
					self.fsCount += 1
					datapath = self.datapaths[dpid]
					ofproto = datapath.ofproto
					parser = datapath.ofproto_parser
					req = parser.OFPFlowStatsRequest(datapath)
					datapath.send_msg(req)
		else:
			self.logger.info("Port is Down")
                if dpid > 3000:
                        print('time',round(time.time() - self.s))
                        print('dpid',dpid)
                        print('port no',port_no)
                        print('free bw',self.free_bandwidth[dpid][port_no])

	def _save_stats(self, _dict, key, value, length=5):
		if key not in _dict:
			_dict[key] = []
		_dict[key].append(value)
		if len(_dict[key]) > length:
			_dict[key].pop(0)

	def _get_speed(self, now, pre, period):
		if period:
			return (now - pre) / (period)
		else:
			return 0

	def _get_free_bw(self, capacity, speed):
		#freebw: Kbit/s
		return max(capacity - speed * 8 / 1000.0, 0)

	def _get_time(self, sec, nsec):
		return sec + nsec / 1000000000.0

	def _get_period(self, n_sec, n_nsec, p_sec, p_nsec):
		return self._get_time(n_sec, n_nsec) - self._get_time(p_sec, p_nsec)

	def show_stat(self, _type):
		'''
			Show statistics information according to data type.
			_type: 'port' / 'flow'
		'''
		if setting.TOSHOW is False:
			return

		bodys = self.stats[_type]
		if _type == 'flow':
			print('\ndatapath  '
				'priority        ip_src        ip_dst  '
				'  packets        bytes  flow-speed(Kb/s)')
			print('--------  '
				'--------  ------------  ------------  '
				'---------  -----------  ----------------')
			for dpid in sorted(bodys.keys()):

				for stat in sorted([flow for flow in bodys[dpid] if ((flow.priority not in [0, 65535]) and (flow.match.get('ipv4_src')) and (flow.match.get('ipv4_dst')))],
						   key=lambda flow: (flow.priority, flow.match.get('ipv4_src'), flow.match.get('ipv4_dst'))):
					print('%8d  %8s  %12s  %12s  %9d  %11d  %16.1f' % (
						dpid,
						stat.priority, stat.match.get('ipv4_src'), stat.match.get('ipv4_dst'),
						stat.packet_count, stat.byte_count,
						abs(self.flow_speed[dpid][(stat.priority, stat.match.get('ipv4_src'), stat.match.get('ipv4_dst'))][-1])*8/1000.0))
			print

		if _type == 'port':
			print('\ndatapath  port '
				'   rx-pkts     rx-bytes ''   tx-pkts     tx-bytes '
				' port-bw(Kb/s)  port-speed(b/s)  port-freebw(Kb/s) '
				' port-state  link-state')
			print('--------  ----  '
				'---------  -----------  ''---------  -----------  '
				'-------------  ---------------  -----------------  '
				'----------  ----------')
			_format = '%8d  %4x  %9d  %11d  %9d  %11d  %13d  %15.1f  %17.1f  %10s  %10s'
			for dpid in sorted(bodys.keys()):
				for stat in sorted(bodys[dpid], key=attrgetter('port_no')):
					if stat.port_no != ofproto_v1_3.OFPP_LOCAL:
						print(_format % (
							dpid, stat.port_no,
							stat.rx_packets, stat.rx_bytes,
							stat.tx_packets, stat.tx_bytes,
							10000,
							abs(self.port_speed[(dpid, stat.port_no)][-1] * 8),
							self.free_bandwidth[dpid][stat.port_no],
							self.port_features[dpid][stat.port_no][0],
							self.port_features[dpid][stat.port_no][1]))
			print
