# Copyright (C) 2021 Maiass Zaher at Budapest University 
# of Technology and Economics, Budapest, Hungary.
# Copyright (C) 2016 Huang MaChi at Chongqing University
# of Posts and Telecommunications, Chongqing, China.
# Copyright (C) 2016 Li Cheng at Beijing University of Posts
# and Telecommunications.
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
This code creates the first layer of Sieves where it resides in data plane.
This layer contains of proactive flow entries and group buckets.
This the data plane created as python code using mininet emulator
where mininet uses TC (traffic control) functions provided in Linux kernel
for emulate BW shaping, delay, loss, etc. 
We evalute Sieve's performance over Fat tree whose size is 4.
Mininet uses Linux containers to create light weight virtual resources like hosts.
In addition, Mininet create OVS switches where use OVS command to create flows, groups, etc.
"""
from mininet.net import Mininet
from mininet.node import Controller, RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import Link, Intf, TCLink
from mininet.topo import Topo
from mininet.util import quietRun
from eventlet import greenthread
from pyexcel_ods import save_data
from collections import OrderedDict
import numpy as np
import threading
import random
import os
import logging
import logging.config
import argparse
import time
import signal
from subprocess import Popen
from multiprocessing import Process
import sys
parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parentdir)
import setting
import tempfile
import copy
#parser = argparse.ArgumentParser(description="Parameters importation")
#parser.add_argument('--k', dest='k', type=int, default=4, choices=[4, 8], help="Switch fanout number")
#parser.add_argument('--trapat', dest='traffic_pattern', help="Traffic pattern of the experiment")
#args = parser.parse_args()

logging.config.fileConfig('logging.conf')
logger=logging.getLogger('fileAndConsole')

class Fattree(Topo):
	"""
		Class of Fattree Topology.
	"""
	CoreSwitchList = []
	AggSwitchList = []
	EdgeSwitchList = []
	HostList = []

	def __init__(self, k, density):
		self.pod = 4
		self.density = density
		self.iCoreLayerSwitch = (k/2)**2
		self.iAggLayerSwitch = k*k/2
		self.iEdgeLayerSwitch = k*k/2
		self.iHost = self.iEdgeLayerSwitch * density

		# Topo initiation
		Topo.__init__(self)

	def createNodes(self):
		self.createCoreLayerSwitch(self.iCoreLayerSwitch)
		self.createAggLayerSwitch(self.iAggLayerSwitch)
		self.createEdgeLayerSwitch(self.iEdgeLayerSwitch)
		self.createHost(self.iHost)

	def _addSwitch(self, number, level, switch_list):
		"""
			Create switches.
		"""
		for i in xrange(1, number+1):
			PREFIX = str(level) + "00"
			if i >= 10:
				PREFIX = str(level) + "0"
			switch_list.append(self.addSwitch(PREFIX + str(i)))

	def createCoreLayerSwitch(self, NUMBER):
		self._addSwitch(NUMBER, 1, self.CoreSwitchList)

	def createAggLayerSwitch(self, NUMBER):
		self._addSwitch(NUMBER, 2, self.AggSwitchList)

	def createEdgeLayerSwitch(self, NUMBER):
		self._addSwitch(NUMBER, 3, self.EdgeSwitchList)

	def createHost(self, NUMBER):
		"""
			Create hosts.
		"""
		for i in xrange(1, NUMBER+1):
			if i >= 100:
				PREFIX = "h"
			elif i >= 10:
				PREFIX = "h0"
			else:
				PREFIX = "h00"
			self.HostList.append(self.addHost(PREFIX + str(i), cpu=1.0/float(NUMBER)))

	def createLinks(self, bw_c2a=20, bw_a2e=20, bw_e2h=20):
		"""
			Add network links.
		"""
		# Core to Agg
		end = self.pod/2
		for x in xrange(0, self.iAggLayerSwitch, end):
			for i in xrange(0, end):
				for j in xrange(0, end):
					self.addLink(
						self.CoreSwitchList[i*end+j],
						self.AggSwitchList[x+i],
						bw=bw_c2a)   # use_htb=False

		# Agg to Edge
		for x in xrange(0, self.iAggLayerSwitch, end):
			for i in xrange(0, end):
				for j in xrange(0, end):
					self.addLink(
						self.AggSwitchList[x+i], self.EdgeSwitchList[x+j],
						bw=bw_a2e, delay='1ms')   # use_htb=False

		# Edge to Host
		for x in xrange(0, self.iEdgeLayerSwitch):
			for i in xrange(0, self.density):
				self.addLink(
					self.EdgeSwitchList[x],
					self.HostList[self.density * x + i],
					bw=bw_e2h, delay='2ms')   # use_htb=False

	def set_ovs_protocol_13(self,):
		"""
			Set the OpenFlow version for switches.
		"""
		self._set_ovs_protocol_13(self.CoreSwitchList)
		self._set_ovs_protocol_13(self.AggSwitchList)
		self._set_ovs_protocol_13(self.EdgeSwitchList)

	def _set_ovs_protocol_13(self, sw_list):
		for sw in sw_list:
		# we set the OpenFlow 1.3 to used by OVS switches
			cmd = "sudo ovs-vsctl set bridge %s protocols=OpenFlow13" % sw
			os.system(cmd)


def set_host_ip(net, topo):
	hostlist = []
	for k in xrange(len(topo.HostList)):
		hostlist.append(net.get(topo.HostList[k]))
	i = 1
	j = 1
	for host in hostlist:
		host.setIP("10.%d.0.%d" % (i, j))
		j += 1
		if j == topo.density+1:
			j = 1
			i += 1

def create_subnetList(topo, num):
	"""
		Create the subnet list of the certain Pod.
	"""
	subnetList = []
	remainder = num % (topo.pod/2)
	if topo.pod == 4:
		if remainder == 0:
			subnetList = [num-1, num]
		elif remainder == 1:
			subnetList = [num, num+1]
		else:
			pass
	elif topo.pod == 8:
		if remainder == 0:
			subnetList = [num-3, num-2, num-1, num]
		elif remainder == 1:
			subnetList = [num, num+1, num+2, num+3]
		elif remainder == 2:
			subnetList = [num-1, num, num+1, num+2]
		elif remainder == 3:
			subnetList = [num-2, num-1, num, num+1]
		else:
			pass
	else:
		pass
	return subnetList

def install_proactive(net, topo):
	"""
		Install proactive flow entries into different layers switches
		according to the upstream and downstream directions.
	"""
	
	##########Edge Switch with buckets###########
	for sw in topo.EdgeSwitchList:
		num = int(sw[-2:])

		# Downstream.
		for i in xrange(1, topo.density+1):
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=1000,arp, \
				nw_dst=10.%d.0.%d,actions=output:%d'" % (sw, num, i, topo.pod/2+i)
                        print('outport',topo.pod/2+i)
			os.system(cmd)
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=1000,ip, \
				nw_dst=10.%d.0.%d,actions=output:%d'" % (sw, num, i, topo.pod/2+i)
			os.system(cmd)

        

		# Upstream.
		# Install group entries to define ECMP scheduling using static packet header hashing.
		if topo.pod == 4:
                        
                        
                        #go to controller
                        cmd = "ovs-ofctl add-group %s -O OpenFlow13 \
                               'group_id=1,type=select,bucket=weight:1,actions:CONTROLLER'" % sw

                       
                       
                        
                        cmd1 = "ovs-ofctl add-group %s -O OpenFlow13 \
                                'group_id=2,type=select,bucket=weight:1,output:1,bucket=weight:1,output:2'" % sw
                        
                       

                        cmd2 = "ovs-ofctl add-group %s -O OpenFlow13\
                                'group_id=3,type=select,bucket=weight:1,output:1,bucket=weight:1,output:2'" % sw




		else:
			pass
		os.system(cmd)
		os.system(cmd1)
		os.system(cmd2)
		# Install flow entries.
		Edge_List = [i for i in xrange(1, 1 + topo.pod ** 2 / 2)]
		for i in Edge_List:
			if i != num:
				for j in xrange(1, topo.pod / 2 + 1):
					for k in xrange(1, topo.pod / 2 + 1):
						cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
						'table=0,idle_timeout=0,hard_timeout=0,priority=10,arp,\
						nw_src=10.%d.0.%d,nw_dst=10.%d.0.%d,actions=group:3'" % (sw, num, j, i, k)
						os.system(cmd)
		Edge_List = [i for i in xrange(1, 1 + topo.pod ** 2 / 2)]
		#print "edge_list", Edge_List
		for i in Edge_List:
			if i != num:
				#print "i:", i
				for j in xrange(1, topo.pod / 2 + 1):
					for k in xrange(1, topo.pod / 2 + 1):
						#print "k:", k
						cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
						'table=0,idle_timeout=0,hard_timeout=0,priority=10,ip,\
						nw_src=10.%d.0.%d,nw_dst=10.%d.0.%d,actions=group:1'" % (sw, num, j, i, k)
						os.system(cmd)
	#	Edge_List = [i for i in xrange(1, 1 + topo.pod ** 2 / 2)]
	#	#print "edge_list", Edge_List
	#	for i in Edge_List:
	#		if i != num:
	#			#print "i:", i
	#			for j in xrange(1, topo.pod / 2 + 1):
	#				for k in xrange(2, topo.pod / 2 + 1):
	#					#print "k:", k
	#					cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
	#					'table=0,idle_timeout=0,hard_timeout=0,priority=10,ip,\
	#					nw_src=10.%d.0.%d,nw_dst=10.%d.0.%d,actions=group:2'" % (sw, num, j, i, k)

	###########Aggregate Switch###########
	for sw in topo.AggSwitchList:
		num = int(sw[-2:])
		subnetList = create_subnetList(topo, num)

		# Downstream.
		k = 1
		for i in subnetList:
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,arp, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, topo.pod/2+k)
			os.system(cmd)
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,ip, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, topo.pod/2+k)
			os.system(cmd)
			k += 1

		# Upstream.
		if topo.pod == 4:
			cmd = "ovs-ofctl add-group %s -O OpenFlow13 \
			'group_id=1,type=select,bucket=output:1,bucket=output:2'" % sw
                        
                        #cmd = "ovs-ofctl add-group %s -O OpenFlow13 \
			#'group_id=1,type=select,bucket=output:1'" % sw

		elif topo.pod == 8:
			cmd = "ovs-ofctl add-group %s -O OpenFlow13 \
			'group_id=1,type=select,bucket=output:1,bucket=output:2,\
			bucket=output:3,bucket=output:4'" % sw
		else:
			pass
		os.system(cmd)
		cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
		'table=0,priority=10,arp,actions=group:1'" % sw
		os.system(cmd)
		cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
		'table=0,priority=10,ip,actions=group:1'" % sw
		os.system(cmd)

	#################Core Switch####################
	for sw in topo.CoreSwitchList:
		j = 1
		k = 1
		for i in xrange(1, len(topo.EdgeSwitchList)+1):
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,arp, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, j)
			os.system(cmd)
			cmd = "ovs-ofctl add-flow %s -O OpenFlow13 \
				'table=0,idle_timeout=0,hard_timeout=0,priority=10,ip, \
				nw_dst=10.%d.0.0/16, actions=output:%d'" % (sw, i, j)
			os.system(cmd)
			k += 1
			if k == topo.pod/2 + 1:
				j += 1
				k = 1

def traffic_generation(net, topo):
	"""
		Start the servers on hosts and invoke the traffic generation files
	"""
	for k in xrange(len(topo.HostList)):
		(net.get(topo.HostList[k])).popen("python -m SimpleHTTPServer 8000 &")
		(net.get(topo.HostList[k])).popen("iperf -s &")
	
	file_tra = './OUR3/'+args.traffic_pattern
	CLI(net, script=file_tra)
	time.sleep(120)
	#os.system('killall iperf')
def UT_Test(net,topo):
    for k in xrange(len(topo.HostList)):
        #(net.get(topo.HostList[k])).popen("python -m SimpleHTTPServer 8000 &")
        (net.get(topo.HostList[k])).popen("iperf -s -i 1 > UT_h"+str(k)," & python -m SimpleHTTPServer ", shell=True)
    
    s=time.time()
    def mice_flow(i,t):
        #while time.time()-s<300:  
        t=t/10
        while t > 0:
            time.sleep(10)
            t=t-1
            s1=time.time()
            for j in xrange(0,100):
                (net.get(topo.HostList[i])).cmdPrint('wget "' + (net.get(topo.HostList[(i+4)%16])).IP() +':8000" ' + '-o mCT_h' + str(i+1) + '_' + str(time.time()-s) + ' &')
    def ele_flow(i):
        while time.time() - s <300:
            print('thread',i)
            
            t=threading.Thread(target=mice_flow,args=(i,40))
            t.setDaemon(True)
            #t.start()
            (net.get(topo.HostList[i])).popen('iperf -c ' + (net.get(topo.HostList[(i+4)%16])).IP() + ' -t 40' + ' > eCT_h' + str(i+1) + '_' + str(round(time.time()-s)),shell=True)
            #t.join() 
    #mt=threading.Thread(target=mice_flow)
    #mt.start()
    threads=[]
    #print('start ele thread')
    for i in xrange(len(topo.HostList)):
        threads.append(threading.Thread(target=ele_flow,args=(i,)))
        threads[i].start()

  #  while time.time()-s<300:
  #      for i in xrange(len(topo.HostList)):
  #          (net.get(topo.HostList[i])).cmdPrint('iperf -c ' + (net.get(topo.HostList[(i+4)%16])).IP() + ' -t ' + str(random.randint(20,60)) + ' -i 1 &')
  #          time.sleep(75)
def test(net,topo):
    s=time.time()
    def mice_flow(i,t=40):
        t=t/10
        while t > 0:
            time.sleep(10)
            t=t-1
            s1=time.time()
            while time.time() - s1 < 1:
                (net.get(topo.HostList[i])).cmdPrint('wget "' + (net.get(topo.HostList[(i+4)%16])).IP() +':8000" ' + '-o mCT_h' + str(i+1) + '_' + str(time.time()-s))
    for k in xrange(len(topo.HostList)):
        (net.get(topo.HostList[k])).popen("iperf -s -i 1 > UT_h"+str(k)," & python -m SimpleHTTPServer ", shell=True)
    threads=[]
        
    for i in xrange(0,12):
        threads.append(threading.Thread(target=mice_flow,args=(i,)))
        threads[i].start()
        threads[i].join()

def my_test(net,topo):
 # create iperf and python server
    net.get(topo.HostList[12]).cmdPrint('iperf -s -p 40000 > server_report/server_report_h13 &')
    net.get(topo.HostList[14]).cmdPrint('iperf -s -p 40000 > server_report/server_report_h15 &')
    net.get(topo.HostList[15]).cmdPrint('iperf -s -p 40000 > server_report/server_report_h16 &')

   
    for i in xrange(0,12):
        (net.get(topo.HostList[i])).cmdPrint('python -m SimpleHTTPServer &')
   
    #cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.7.0.1,actions=output:"3001-eth2"'
    #cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.7.0.1,actions=output:"3001-eth2"'
    #cmd3='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.7.0.1,actions=output:"3002-eth2"'
    #cmd4='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.7.0.1,actions=output:"3002-eth2"'
    cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.7.0.1,tcp,tp_src=8000,actions=output:"3001-eth1"'
    cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.7.0.1,tcp,tp_src=8000,actions=output:"3001-eth"'
    cmd3='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.7.0.1,tcp,tp_src=8000,actions=output:"3002-eth1"'
    cmd4='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.7.0.1,tcp,tp_src=8000,actions=output:"3002-eth1"'
    cmd5='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth3",nw_src=10.3.0.1,nw_dst=10.8.0.1,tcp,tp_src=8000,actions=output:"3003-eth1"'
    cmd6='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth4",nw_src=10.3.0.2,nw_dst=10.8.0.1,tcp,tp_src=8000,actions=output:"3003-eth1"'
    cmd7='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth3",nw_src=10.4.0.1,nw_dst=10.8.0.1,tcp,tp_src=8000,actions=output:"3004-eth1"'
    cmd8='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth4",nw_src=10.4.0.2,nw_dst=10.8.0.1,tcp,tp_src=8000,actions=output:"3004-eth1"'
    cmd9='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth3",nw_src=10.5.0.1,nw_dst=10.8.0.2,tcp,tp_src=8000,actions=output:"3005-eth1"'
    cmd10='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth4",nw_src=10.5.0.2,nw_dst=10.8.0.2,tcp,tp_src=8000,actions=output:"3005-eth1"'
    cmd11='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.2,tcp,tp_src=8000,actions=output:"3006-eth1"'
    cmd12='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth4",nw_src=10.6.0.2,nw_dst=10.8.0.2,tcp,tp_src=8000,actions=output:"3006-eth1"'
   # cmd3='ovs-ofctl add-flow 2001 -O OpenFlow13 table=0,priority=1000,ip,in_port="2001-eth3",nw_src=10.1.0.1,nw_dst=10.8.0.1,actions=output:"2001-eth1"'
   # #cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=1000,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.8.0.1,actions=output:"3001-eth1"'
   # #cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=1000,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.8.0.2,actions=output:"3001-eth1"'
    #os.system(cmd)
    #os.system(cmd2)
    #os.system(cmd3)
    #os.system(cmd4)
    #os.system(cmd5)
    #os.system(cmd6)
    #os.system(cmd7)
    #os.system(cmd8)
    #os.system(cmd9)
    #os.system(cmd10)
    #os.system(cmd11)
    #os.system(cmd12)
    s=time.time()

    cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3001-eth1"'
    cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3001-eth2"'
    cmd3='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3002-eth1"'
    cmd4='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3002-eth2"'
    cmd5='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth3",nw_src=10.3.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3003-eth1"'
    cmd6='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth4",nw_src=10.3.0.2,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3003-eth2"'
    cmd7='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth3",nw_src=10.4.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3004-eth1"'
    cmd8='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth4",nw_src=10.4.0.2,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3004-eth2"'
    cmd9='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth3",nw_src=10.5.0.1,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3005-eth1"'
    cmd10='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth4",nw_src=10.5.0.2,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3005-eth2"'
    cmd11='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3006-eth1"'
    cmd12='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth4",nw_src=10.6.0.2,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3006-eth2"'

    #os.system(cmd)
    #os.system(cmd2)
    #os.system(cmd3)
    #os.system(cmd4)
    #os.system(cmd5)
    #os.system(cmd6)
    #os.system(cmd7)
    #os.system(cmd8)
    #os.system(cmd9)
    #os.system(cmd10)
    #os.system(cmd11)
    #os.system(cmd12)
    
    cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3001-eth2"'
    cmd2='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3002-eth2"'
    cmd3='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3003-eth3",nw_src=10.3.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3003-eth2"'
    cmd4='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3004-eth3",nw_src=10.4.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3004-eth2"'
    cmd5='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3005-eth3",nw_src=10.5.0.1,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3005-eth2"'
    cmd6='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3006-eth2"'
    cmd7='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3001-eth2"'
    cmd8='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3002-eth2"'
    cmd9='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3003-eth4",nw_src=10.3.0.2,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3003-eth2"'
    cmd10='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3004-eth4",nw_src=10.4.0.2,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3004-eth2"'
    cmd11='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3005-eth4",nw_src=10.5.0.2,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3005-eth2"'
    cmd12='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3006-eth4",nw_src=10.6.0.2,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3006-eth2"'
   

    def generate_mice_flow():
        t=4
        j=4
        #time.sleep(15)
        #os.system(cmd)
        #os.system(cmd2)
        #os.system(cmd3)
        #os.system(cmd4)



        print('start mice thread')
        while j > 0:
            time.sleep(5)
            j=j-1
            #os.system(cmd)
            #os.system(cmd2)
            #os.system(cmd3)
            #os.system(cmd4)
            #os.system(cmd5)
            #os.system(cmd6)
            #os.system(cmd7)
            #os.system(cmd8)
            #os.system(cmd9)
            #os.system(cmd10)
            #os.system(cmd11)
            #os.system(cmd12)


            net.get(topo.HostList[12]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h1' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[12]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h2' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[12]).cmdPrint('wget 10.2.0.1:8000 -o mice_flow/mCT_h3' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[12]).cmdPrint('wget 10.2.0.2:8000 -o mice_flow/mCT_h4' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[14]).cmdPrint('wget 10.3.0.1:8000 -o mice_flow/mCT_h5' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[14]).cmdPrint('wget 10.3.0.2:8000 -o mice_flow/mCT_h6' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[14]).cmdPrint('wget 10.4.0.1:8000 -o mice_flow/mCT_h7' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[14]).cmdPrint('wget 10.4.0.2:8000 -o mice_flow/mCT_h8' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[15]).cmdPrint('wget 10.5.0.1:8000 -o mice_flow/mCT_h9' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[15]).cmdPrint('wget 10.5.0.2:8000 -o mice_flow/mCT_h10' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[15]).cmdPrint('wget 10.6.0.1:8000 -o mice_flow/mCT_h11' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[15]).cmdPrint('wget 10.6.0.2:8000 -o mice_flow/mCT_h12' + '_' + str(round(time.time()-s)) + ' &')

        #while t > 0:
        #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.2 -n 200000 -l 200000 > h2_report_'+ str(round(time.time()-s)) + ' &')
        #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.2 -n 300000 > h2_report_'+ str(round(time.time()-s)) + ' &')
        #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.2 -n 500000 > h2_report_'+ str(round(time.time()-s)) + ' &')

                #t=t-1
   # mice_thread=threading.Thread(target=generate_mice_flow)
   # mice_thread.start() 
   # net.get(topo.HostList[0]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h1_report &')
   # net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h2_report &')
   # net.get(topo.HostList[2]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h3_report &')
   # net.get(topo.HostList[3]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h4_report &')
    def generate_elephant_flow():
        print('start ele thread')
        while time.time() - s < 300:
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 > h1_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 > h2_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[2]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 > h3_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[3]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 > h4_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[4]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 > h5_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[5]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 > h6_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[6]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 > h7_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[7]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 > h8_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[8]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 > h9_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[9]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 > h10_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[10]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 > h11_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[11]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )
            
            #t=threading.Thread(target=generate_mice_flow)

            generate_mice_flow()
            
            #if time.time()-s > 250:
            #    s_time=1
            #else:
            #    s_time=60
                
            time.sleep(25)
    
    generate_elephant_flow()
num_ele=0
num_mice=0

def u_my_test(net,topo):
 # create iperf and python server
    net.get(topo.HostList[12]).cmdPrint('iperf -s -p 40000 -u > server_report/server_report_h13 &')
    net.get(topo.HostList[14]).cmdPrint('iperf -s -p 40000 -u > server_report/server_report_h15 &')
    net.get(topo.HostList[15]).cmdPrint('iperf -s -p 40000 -u > server_report/server_report_h16 &')

   
    for i in xrange(0,12):
        (net.get(topo.HostList[i])).cmdPrint('python -m SimpleHTTPServer &')
   
    #cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.7.0.1,actions=output:"3001-eth2"'
    #cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.7.0.1,actions=output:"3001-eth2"'
    #cmd3='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.7.0.1,actions=output:"3002-eth2"'
    #cmd4='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.7.0.1,actions=output:"3002-eth2"'
    cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.7.0.1,tcp,tp_src=8000,actions=output:"3001-eth1"'
    cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.7.0.1,tcp,tp_src=8000,actions=output:"3001-eth"'
    cmd3='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.7.0.1,tcp,tp_src=8000,actions=output:"3002-eth1"'
    cmd4='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.7.0.1,tcp,tp_src=8000,actions=output:"3002-eth1"'
    cmd5='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth3",nw_src=10.3.0.1,nw_dst=10.8.0.1,tcp,tp_src=8000,actions=output:"3003-eth1"'
    cmd6='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth4",nw_src=10.3.0.2,nw_dst=10.8.0.1,tcp,tp_src=8000,actions=output:"3003-eth1"'
    cmd7='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth3",nw_src=10.4.0.1,nw_dst=10.8.0.1,tcp,tp_src=8000,actions=output:"3004-eth1"'
    cmd8='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth4",nw_src=10.4.0.2,nw_dst=10.8.0.1,tcp,tp_src=8000,actions=output:"3004-eth1"'
    cmd9='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth3",nw_src=10.5.0.1,nw_dst=10.8.0.2,tcp,tp_src=8000,actions=output:"3005-eth1"'
    cmd10='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth4",nw_src=10.5.0.2,nw_dst=10.8.0.2,tcp,tp_src=8000,actions=output:"3005-eth1"'
    cmd11='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.2,tcp,tp_src=8000,actions=output:"3006-eth1"'
    cmd12='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth4",nw_src=10.6.0.2,nw_dst=10.8.0.2,tcp,tp_src=8000,actions=output:"3006-eth1"'
   # cmd3='ovs-ofctl add-flow 2001 -O OpenFlow13 table=0,priority=1000,ip,in_port="2001-eth3",nw_src=10.1.0.1,nw_dst=10.8.0.1,actions=output:"2001-eth1"'
   # #cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=1000,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.8.0.1,actions=output:"3001-eth1"'
   # #cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=1000,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.8.0.2,actions=output:"3001-eth1"'
    #os.system(cmd)
    #os.system(cmd2)
    #os.system(cmd3)
    #os.system(cmd4)
    #os.system(cmd5)
    #os.system(cmd6)
    #os.system(cmd7)
    #os.system(cmd8)
    #os.system(cmd9)
    #os.system(cmd10)
    #os.system(cmd11)
    #os.system(cmd12)
    s=time.time()

    cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3001-eth1"'
    cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3001-eth2"'
    cmd3='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3002-eth1"'
    cmd4='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3002-eth2"'
    cmd5='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth3",nw_src=10.3.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3003-eth1"'
    cmd6='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth4",nw_src=10.3.0.2,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3003-eth2"'
    cmd7='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth3",nw_src=10.4.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3004-eth1"'
    cmd8='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth4",nw_src=10.4.0.2,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3004-eth2"'
    cmd9='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth3",nw_src=10.5.0.1,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3005-eth1"'
    cmd10='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth4",nw_src=10.5.0.2,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3005-eth2"'
    cmd11='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3006-eth1"'
    cmd12='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth4",nw_src=10.6.0.2,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3006-eth2"'

    #os.system(cmd)
    #os.system(cmd2)
    #os.system(cmd3)
    #os.system(cmd4)
    #os.system(cmd5)
    #os.system(cmd6)
    #os.system(cmd7)
    #os.system(cmd8)
    #os.system(cmd9)
    #os.system(cmd10)
    #os.system(cmd11)
    #os.system(cmd12)
    
    cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3001-eth2"'
    cmd2='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3002-eth2"'
    cmd3='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3003-eth3",nw_src=10.3.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3003-eth2"'
    cmd4='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3004-eth3",nw_src=10.4.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3004-eth2"'
    cmd5='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3005-eth3",nw_src=10.5.0.1,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3005-eth2"'
    cmd6='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3006-eth2"'
    cmd7='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3001-eth2"'
    cmd8='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3002-eth2"'
    cmd9='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3003-eth4",nw_src=10.3.0.2,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3003-eth2"'
    cmd10='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3004-eth4",nw_src=10.4.0.2,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3004-eth2"'
    cmd11='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3005-eth4",nw_src=10.5.0.2,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3005-eth2"'
    cmd12='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,hard_timeout=5,priority=60,ip,in_port="3006-eth4",nw_src=10.6.0.2,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3006-eth2"'
   

    def generate_mice_flow():
        t=4
        j=4
        #time.sleep(15)
        #os.system(cmd)
        #os.system(cmd2)
        #os.system(cmd3)
        #os.system(cmd4)



        print('start mice thread')
        while j > 0:
            time.sleep(5)
            j=j-1
            #os.system(cmd)
            #os.system(cmd2)
            #os.system(cmd3)
            #os.system(cmd4)
            #os.system(cmd5)
            #os.system(cmd6)
            #os.system(cmd7)
            #os.system(cmd8)
            #os.system(cmd9)
            #os.system(cmd10)
            #os.system(cmd11)
            #os.system(cmd12)


            net.get(topo.HostList[12]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h1' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[12]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h2' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[12]).cmdPrint('wget 10.2.0.1:8000 -o mice_flow/mCT_h3' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[12]).cmdPrint('wget 10.2.0.2:8000 -o mice_flow/mCT_h4' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[14]).cmdPrint('wget 10.3.0.1:8000 -o mice_flow/mCT_h5' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[14]).cmdPrint('wget 10.3.0.2:8000 -o mice_flow/mCT_h6' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[14]).cmdPrint('wget 10.4.0.1:8000 -o mice_flow/mCT_h7' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[14]).cmdPrint('wget 10.4.0.2:8000 -o mice_flow/mCT_h8' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[15]).cmdPrint('wget 10.5.0.1:8000 -o mice_flow/mCT_h9' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[15]).cmdPrint('wget 10.5.0.2:8000 -o mice_flow/mCT_h10' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[15]).cmdPrint('wget 10.6.0.1:8000 -o mice_flow/mCT_h11' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[15]).cmdPrint('wget 10.6.0.2:8000 -o mice_flow/mCT_h12' + '_' + str(round(time.time()-s)) + ' &')

        #while t > 0:
        #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.2 -n 200000 -l 200000 > h2_report_'+ str(round(time.time()-s)) + ' &')
        #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.2 -n 300000 > h2_report_'+ str(round(time.time()-s)) + ' &')
        #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.2 -n 500000 > h2_report_'+ str(round(time.time()-s)) + ' &')

                #t=t-1
   # mice_thread=threading.Thread(target=generate_mice_flow)
   # mice_thread.start() 
   # net.get(topo.HostList[0]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h1_report &')
   # net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h2_report &')
   # net.get(topo.HostList[2]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h3_report &')
   # net.get(topo.HostList[3]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h4_report &')
    def generate_elephant_flow():
        print('start ele thread')
        while time.time() - s < 300:
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 -u > h1_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 -u > h1_report_'+ str(round(time.time()-s)) + ' &' )

            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 -u > h2_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 -u > h2_report_'+ str(round(time.time()-s)) + ' &' )           
            net.get(topo.HostList[2]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 -u > h3_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[2]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 -u > h3_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[3]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 -u > h4_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[3]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 -u > h4_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[4]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 -u > h5_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[4]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 -u > h5_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[5]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 -u > h6_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[5]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 -u > h6_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[6]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 -u > h7_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[6]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 -u > h7_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[7]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 -u > h8_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[7]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 -u > h8_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[8]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 -u > h9_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[8]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 -u > h9_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[9]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 -u > h10_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[9]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 -u > h10_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[10]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 -u > h11_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[10]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 -u > h11_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[11]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 -u > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[11]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 -u > h12_report_'+ str(round(time.time()-s)) + ' &' )
            
            #t=threading.Thread(target=generate_mice_flow)

            generate_mice_flow()
            
            #if time.time()-s > 250:
            #    s_time=1
            #else:
            #    s_time=60
                
            #time.sleep(5)
    
    generate_elephant_flow()
num_ele=0
num_mice=0

def my_test2(net,topo):
 # create iperf and python server
    collect_mice_time=[]
    collect_ele_num=[]
    collect_mice_num=[]
    collect_ele_time=[]

    for i in xrange(0,16):
        net.get(topo.HostList[i]).cmdPrint('iperf -s -p 40000 > server_report/server_report_h' + str(i+1) + ' &')

   
    for i in xrange(0,16):
        (net.get(topo.HostList[i])).cmdPrint('python -m SimpleHTTPServer &')
   
    #cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.7.0.1,actions=output:"3001-eth2"'
    #cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.7.0.1,actions=output:"3001-eth2"'
    #cmd3='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.7.0.1,actions=output:"3002-eth2"'
    #cmd4='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.7.0.1,actions=output:"3002-eth2"'
    cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.3.0.1,tcp,tp_src=8000,actions=output:"3001-eth1"'
    cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.3.0.2,tcp,tp_src=8000,actions=output:"3001-eth1"'
    cmd3='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.4.0.1,tcp,tp_src=8000,actions=output:"3002-eth1"'
    cmd4='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.4.0.2,tcp,tp_src=8000,actions=output:"3002-eth1"'
    cmd5='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth3",nw_src=10.3.0.1,nw_dst=10.5.0.1,tcp,tp_src=8000,actions=output:"3003-eth1"'
    cmd6='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth4",nw_src=10.3.0.2,nw_dst=10.5.0.2,tcp,tp_src=8000,actions=output:"3003-eth1"'
    cmd7='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth3",nw_src=10.4.0.1,nw_dst=10.6.0.1,tcp,tp_src=8000,actions=output:"3004-eth1"'
    cmd8='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth4",nw_src=10.4.0.2,nw_dst=10.6.0.2,tcp,tp_src=8000,actions=output:"3004-eth1"'
    cmd9='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth3",nw_src=10.5.0.1,nw_dst=10.7.0.1,tcp,tp_src=8000,actions=output:"3005-eth1"'
    cmd10='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth4",nw_src=10.5.0.2,nw_dst=10.7.0.2,tcp,tp_src=8000,actions=output:"3005-eth1"'
    cmd11='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.1,tcp,tp_src=8000,actions=output:"3006-eth1"'
    cmd12='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth4",nw_src=10.6.0.2,nw_dst=10.8.0.2,tcp,tp_src=8000,actions=output:"3006-eth1"'
    cmd13='ovs-ofctl add-flow 3007 -O OpenFlow13 table=0,priority=50,ip,in_port="3007-eth3",nw_src=10.7.0.1,nw_dst=10.1.0.1,tcp,tp_src=8000,actions=output:"3007-eth1"'
    cmd14='ovs-ofctl add-flow 3007 -O OpenFlow13 table=0,priority=50,ip,in_port="3007-eth4",nw_src=10.7.0.2,nw_dst=10.1.0.2,tcp,tp_src=8000,actions=output:"3007-eth1"'
    cmd15='ovs-ofctl add-flow 3008 -O OpenFlow13 table=0,priority=50,ip,in_port="3008-eth3",nw_src=10.8.0.1,nw_dst=10.2.0.1,tcp,tp_src=8000,actions=output:"3008-eth1"'
    cmd16='ovs-ofctl add-flow 3008 -O OpenFlow13 table=0,priority=50,ip,in_port="3008-eth4",nw_src=10.8.0.2,nw_dst=10.2.0.2,tcp,tp_src=8000,actions=output:"3008-eth1"'
   # cmd3='ovs-ofctl add-flow 2001 -O OpenFlow13 table=0,priority=1000,ip,in_port="2001-eth3",nw_src=10.1.0.1,nw_dst=10.8.0.1,actions=output:"2001-eth1"'
   # #cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=1000,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.8.0.1,actions=output:"3001-eth1"'
   # #cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=1000,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.8.0.2,actions=output:"3001-eth1"'
    #os.system(cmd)
    #os.system(cmd2)
    #os.system(cmd3)
    #os.system(cmd4)
    #os.system(cmd5)
    #os.system(cmd6)
    #os.system(cmd7)
    #os.system(cmd8)
    #os.system(cmd9)
    #os.system(cmd10)
    #os.system(cmd11)
    #os.system(cmd12)
    #os.system(cmd13)
    #os.system(cmd14)
    #os.system(cmd15)
    #os.system(cmd16)
    s=time.time()

    cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.3.0.1,tcp,tp_dst=40000,actions=output:"3001-eth1"'
    cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.3.0.2,tcp,tp_dst=40000,actions=output:"3001-eth2"'
    cmd3='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.4.0.1,tcp,tp_dst=40000,actions=output:"3002-eth1"'
    cmd4='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.4.0.2,tcp,tp_dst=40000,actions=output:"3002-eth2"'
    cmd5='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth3",nw_src=10.3.0.1,nw_dst=10.5.0.1,tcp,tp_dst=40000,actions=output:"3003-eth1"'
    cmd6='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth4",nw_src=10.3.0.2,nw_dst=10.5.0.2,tcp,tp_dst=40000,actions=output:"3003-eth2"'
    cmd7='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth3",nw_src=10.4.0.1,nw_dst=10.6.0.1,tcp,tp_dst=40000,actions=output:"3004-eth1"'
    cmd8='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth4",nw_src=10.4.0.2,nw_dst=10.6.0.2,tcp,tp_dst=40000,actions=output:"3004-eth2"'
    cmd9='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth3",nw_src=10.5.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3005-eth1"'
    cmd10='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth4",nw_src=10.5.0.2,nw_dst=10.7.0.2,tcp,tp_dst=40000,actions=output:"3005-eth2"'
    cmd11='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3006-eth1"'
    cmd12='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth4",nw_src=10.6.0.2,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3006-eth2"'
    cmd13='ovs-ofctl add-flow 3007 -O OpenFlow13 table=0,priority=50,ip,in_port="3007-eth3",nw_src=10.7.0.1,nw_dst=10.1.0.1,tcp,tp_dst=40000,actions=output:"3007-eth1"'
    cmd14='ovs-ofctl add-flow 3007 -O OpenFlow13 table=0,priority=50,ip,in_port="3007-eth4",nw_src=10.7.0.2,nw_dst=10.1.0.2,tcp,tp_dst=40000,actions=output:"3007-eth2"'
    cmd15='ovs-ofctl add-flow 3008 -O OpenFlow13 table=0,priority=50,ip,in_port="3008-eth3",nw_src=10.8.0.1,nw_dst=10.2.0.1,tcp,tp_dst=40000,actions=output:"3008-eth1"'
    cmd16='ovs-ofctl add-flow 3008 -O OpenFlow13 table=0,priority=50,ip,in_port="3008-eth4",nw_src=10.8.0.2,nw_dst=10.2.0.2,tcp,tp_dst=40000,actions=output:"3008-eth2"'

    #os.system(cmd)
    #os.system(cmd2)
    #os.system(cmd3)
    #os.system(cmd4)
    #os.system(cmd5)
    #os.system(cmd6)
    #os.system(cmd7)
    #os.system(cmd8)
    #os.system(cmd9)
    #os.system(cmd10)
    #os.system(cmd11)
    #os.system(cmd12)
    #os.system(cmd13)
    #os.system(cmd14)
    #os.system(cmd15)
    #os.system(cmd16)
    
    cmd='ovs-ofctl add-flow 2001 -O OpenFlow13 table=0,priority=50,ip,in_port="2001-eth3",nw_src=10.1.0.1,nw_dst=10.3.0.1,tcp,tp_dst=40000,actions=output:"2001-eth2"'
    cmd2='ovs-ofctl add-flow 2001 -O OpenFlow13 table=0,priority=50,ip,in_port="2001-eth4",nw_src=10.1.0.2,nw_dst=10.3.0.2,tcp,tp_dst=40000,actions=output:"3001-eth2"'
    cmd3='ovs-ofctl add-flow 2002 -O OpenFlow13 table=0,priority=50,ip,in_port="2002-eth3",nw_src=10.2.0.1,nw_dst=10.4.0.1,tcp,tp_dst=40000,actions=output:"3002-eth2"'
    cmd4='ovs-ofctl add-flow 2002 -O OpenFlow13 table=0,priority=50,ip,in_port="2002-eth4",nw_src=10.2.0.2,nw_dst=10.4.0.2,tcp,tp_dst=40000,actions=output:"3002-eth2"'
    cmd5='ovs-ofctl add-flow 2003 -O OpenFlow13 table=0,priority=50,ip,in_port="2003-eth3",nw_src=10.3.0.1,nw_dst=10.5.0.1,tcp,tp_dst=40000,actions=output:"3003-eth2"'
    cmd6='ovs-ofctl add-flow 2003 -O OpenFlow13 table=0,priority=50,ip,in_port="2003-eth4",nw_src=10.3.0.2,nw_dst=10.5.0.2,tcp,tp_dst=40000,actions=output:"3003-eth2"'
    cmd7='ovs-ofctl add-flow 2004 -O OpenFlow13 table=0,priority=50,ip,in_port="2004-eth3",nw_src=10.4.0.1,nw_dst=10.6.0.1,tcp,tp_dst=40000,actions=output:"3004-eth2"'
    cmd8='ovs-ofctl add-flow 2004 -O OpenFlow13 table=0,priority=50,ip,in_port="2004-eth4",nw_src=10.4.0.2,nw_dst=10.6.0.2,tcp,tp_dst=40000,actions=output:"3004-eth2"'
    cmd9='ovs-ofctl add-flow 2005 -O OpenFlow13 table=0,priority=50,ip,in_port="2005-eth3",nw_src=10.5.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3005-eth2"'
    cmd10='ovs-ofctl add-flow 2005 -O OpenFlow13 table=0,priority=50,ip,in_port="2005-eth4",nw_src=10.5.0.2,nw_dst=10.7.0.2,tcp,tp_dst=40000,actions=output:"3005-eth2"'
    cmd11='ovs-ofctl add-flow 2006 -O OpenFlow13 table=0,priority=50,ip,in_port="2006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3006-eth2"'
    cmd12='ovs-ofctl add-flow 2006 -O OpenFlow13 table=0,priority=50,ip,in_port="2006-eth4",nw_src=10.6.0.2,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3006-eth2"'
    cmd13='ovs-ofctl add-flow 2007 -O OpenFlow13 table=0,priority=50,ip,in_port="2007-eth3",nw_src=10.7.0.1,nw_dst=10.1.0.1,tcp,tp_dst=40000,actions=output:"3007-eth2"'
    cmd14='ovs-ofctl add-flow 2007 -O OpenFlow13 table=0,priority=50,ip,in_port="2007-eth4",nw_src=10.7.0.2,nw_dst=10.1.0.2,tcp,tp_dst=40000,actions=output:"3007-eth2"'
    cmd15='ovs-ofctl add-flow 2008 -O OpenFlow13 table=0,priority=50,ip,in_port="2008-eth3",nw_src=10.8.0.1,nw_dst=10.2.0.1,tcp,tp_dst=40000,actions=output:"3008-eth2"'
    cmd16='ovs-ofctl add-flow 2008 -O OpenFlow13 table=0,priority=50,ip,in_port="2008-eth4",nw_src=10.8.0.2,nw_dst=10.2.0.2,tcp,tp_dst=40000,actions=output:"3008-eth2"'

    #os.system(cmd)
    #os.system(cmd2)
    #os.system(cmd3)
    #os.system(cmd4)
    #os.system(cmd5)
    #os.system(cmd6)
    #os.system(cmd7)
    #os.system(cmd8)
    #os.system(cmd9)
    #os.system(cmd10)
    #os.system(cmd11)
    #os.system(cmd12)
    #os.system(cmd13)
    #os.system(cmd14)
    #os.system(cmd15)
    #os.system(cmd16)

    cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.3.0.1,tcp,tp_dst=40000,actions=output:"3001-eth2"'
    cmd2='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.4.0.1,tcp,tp_dst=40000,actions=output:"3002-eth2"'
    cmd3='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3003-eth3",nw_src=10.3.0.1,nw_dst=10.5.0.1,tcp,tp_dst=40000,actions=output:"3003-eth2"'
    cmd4='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3004-eth3",nw_src=10.4.0.1,nw_dst=10.6.0.1,tcp,tp_dst=40000,actions=output:"3004-eth2"'
    cmd5='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3005-eth3",nw_src=10.5.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3005-eth2"'
    cmd6='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3006-eth2"'
    cmd7='ovs-ofctl add-flow 3007 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3007-eth3",nw_src=10.7.0.1,nw_dst=10.1.0.1,tcp,tp_dst=40000,actions=output:"3007-eth2"'
    cmd8='ovs-ofctl add-flow 3008 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3008-eth3",nw_src=10.8.0.1,nw_dst=10.2.0.1,tcp,tp_dst=40000,actions=output:"3008-eth2"'
   
    def generate_mice_flow(ele_time):
        t=4
        j=4
        #time.sleep(15)
        #os.system(cmd)
        #os.system(cmd2)
        #os.system(cmd3)
        #os.system(cmd4)



        print('start mice thread')

        while j > 0:
            global num_mice
            global num_ele
            time.sleep(5)
            j=j-1
            #os.system(cmd)
            #os.system(cmd2)
            #os.system(cmd3)
            #os.system(cmd4)
            #os.system(cmd5)
            #os.system(cmd6)
            #os.system(cmd7)
            #os.system(cmd8)
 
            logger.info('generate mice flow')

            net.get(topo.HostList[4]).cmdPrint('wget 10.5.0.1:8000 -o mice_flow/mCT_h1' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)
            

            net.get(topo.HostList[5]).cmdPrint('wget 10.5.0.2:8000 -o mice_flow/mCT_h2' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[6]).cmdPrint('wget 10.6.0.1:8000 -o mice_flow/mCT_h3' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[7]).cmdPrint('wget 10.6.0.2:8000 -o mice_flow/mCT_h4' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[8]).cmdPrint('wget 10.7.0.1:8000 -o mice_flow/mCT_h5' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[9]).cmdPrint('wget 10.7.0.2:8000 -o mice_flow/mCT_h6' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[10]).cmdPrint('wget 10.8.0.1:8000 -o mice_flow/mCT_h7' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[11]).cmdPrint('wget 10.8.0.2:8000 -o mice_flow/mCT_h8' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[12]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h9' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[13]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h10' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[14]).cmdPrint('wget 10.2.0.1:8000 -o mice_flow/mCT_h11' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[15]).cmdPrint('wget 10.2.0.2:8000 -o mice_flow/mCT_h12' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[0]).cmdPrint('wget 10.3.0.1:8000 -o mice_flow/mCT_h13' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[1]).cmdPrint('wget 10.3.0.2:8000 -o mice_flow/mCT_h14' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[2]).cmdPrint('wget 10.4.0.1:8000 -o mice_flow/mCT_h15' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)

            net.get(topo.HostList[3]).cmdPrint('wget 10.4.0.2:8000 -o mice_flow/mCT_h16' + '_' + str(round(time.time()-s)) + ' &')
            num_mice=num_mice+1
            collect_mice_time.append(round(time.time()-s)+20)
            collect_mice_num.append(num_mice)
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele_time)
        #while t > 0:
        #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.2 -n 200000 -l 200000 > h2_report_'+ str(round(time.time()-s)) + ' &')
        #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.2 -n 300000 > h2_report_'+ str(round(time.time()-s)) + ' &')
        #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.2 -n 500000 > h2_report_'+ str(round(time.time()-s)) + ' &')

                #t=t-1
   # mice_thread=threading.Thread(target=generate_mice_flow)
   # mice_thread.start() 
   # net.get(topo.HostList[0]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h1_report &')
   # net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h2_report &')
   # net.get(topo.HostList[2]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h3_report &')
   # net.get(topo.HostList[3]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h4_report &')
    def generate_elephant_flow():
        global num_ele
        print('start ele thread')
        while time.time() - s < 300:
            logger.info('generate elephant flow')
            ele_time=round(time.time())
            ele=round(time.time()-s)
            #net.get(topo.HostList[0]).cmdPrint('iperf -c 10.3.0.1 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h1_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.3.0.1 -t 40 -p 40000 -i 1 > h1_report_'+ str(round(time.time()-s)) + ' &' )

            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])


            #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.3.0.2 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h2_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.3.0.2 -t 40 -p 40000 -i 1 > h2_report_'+ str(round(time.time()-s)) + ' &' )
            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])


            #net.get(topo.HostList[2]).cmdPrint('iperf -c 10.4.0.1 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h3_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[2]).cmdPrint('iperf -c 10.4.0.1 -t 40 -p 40000 -i 1 > h3_report_'+ str(round(time.time()-s)) + ' &' )

            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])


            #net.get(topo.HostList[3]).cmdPrint('iperf -c 10.4.0.2 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h4_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[3]).cmdPrint('iperf -c 10.4.0.2 -t 40 -p 40000 -i 1 > h4_report_'+ str(round(time.time()-s)) + ' &' )
            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])

            #net.get(topo.HostList[4]).cmdPrint('iperf -c 10.5.0.1 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h5_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[4]).cmdPrint('iperf -c 10.5.0.1 -t 40 -p 40000 -i 1 > h5_report_'+ str(round(time.time()-s)) + ' &' )

            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])

            #net.get(topo.HostList[5]).cmdPrint('iperf -c 10.5.0.2 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h6_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[5]).cmdPrint('iperf -c 10.5.0.2 -t 40 -p 40000 -i 1 > h6_report_'+ str(round(time.time()-s)) + ' &' )
            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])

            #net.get(topo.HostList[6]).cmdPrint('iperf -c 10.6.0.1 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h7_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[6]).cmdPrint('iperf -c 10.6.0.1 -t 40 -p 40000 -i 1 > h7_report_'+ str(round(time.time()-s)) + ' &' )

            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])

            #net.get(topo.HostList[7]).cmdPrint('iperf -c 10.6.0.2 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h8_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[7]).cmdPrint('iperf -c 10.6.0.2 -t 40 -p 40000 -i 1 > h8_report_'+ str(round(time.time()-s)) + ' &' )
            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])

            #net.get(topo.HostList[8]).cmdPrint('iperf -c 10.7.0.1 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h9_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[8]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 > h9_report_'+ str(round(time.time()-s)) + ' &' )

            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])

            #net.get(topo.HostList[9]).cmdPrint('iperf -c 10.7.0.2 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h10_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[9]).cmdPrint('iperf -c 10.7.0.2 -t 40 -p 40000 -i 1 > h10_report_'+ str(round(time.time()-s)) + ' &' )
            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])

            #net.get(topo.HostList[10]).cmdPrint('iperf -c 10.8.0.1 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h11_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[10]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 > h11_report_'+ str(round(time.time()-s)) + ' &' )

            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])

            #net.get(topo.HostList[11]).cmdPrint('iperf -c 10.8.0.2 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[11]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )
            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])

            #net.get(topo.HostList[12]).cmdPrint('iperf -c 10.1.0.1 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[12]).cmdPrint('iperf -c 10.1.0.1 -t 40 -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )

            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])

            #net.get(topo.HostList[13]).cmdPrint('iperf -c 10.1.0.2 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[13]).cmdPrint('iperf -c 10.1.0.2 -t 40 -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )
            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])

            #net.get(topo.HostList[14]).cmdPrint('iperf -c 10.2.0.1 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[14]).cmdPrint('iperf -c 10.2.0.1 -t 40 -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )

            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])

            #net.get(topo.HostList[15]).cmdPrint('iperf -c 10.2.0.2 -t ' + str(random.randint(20,60)) + ' -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[15]).cmdPrint('iperf -c 10.2.0.2 -t 40 -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )
            num_ele=num_ele+1
            collect_ele_num.append(num_ele)
            collect_ele_time.append(ele)
            if len(collect_mice_num)==0:
                collect_mice_num.append(0)
            else:
                collect_mice_num.append(collect_mice_num[-1])
            if len(collect_mice_time)==0:
                collect_mice_time.append(10)
            else:
                collect_mice_time.append(collect_mice_time[-1])

            #t=threading.Thread(target=generate_mice_flow)

            generate_mice_flow(round(time.time()-s))
           # if round(time.time()-s) < 100:
           #     sleep_time=5
           # else:
           #     sleep_time=5
           # print('sleep time',sleep_time)
            time.sleep(25)
     
    generate_elephant_flow()
    data=OrderedDict()
    data2=OrderedDict()
    data3=OrderedDict()
    data4=OrderedDict()

    data.update({"Sheet 1": [collect_mice_time]})
    save_data("mice time.ods",data)
    data2.update({"Sheet 1": [collect_mice_num]})
    save_data("mice num.ods",data2)
    data3.update({"Sheet 1": [collect_ele_num]})
    save_data("ele num.ods",data3)
    data4.update({"Sheet 1": [collect_ele_time]})
    save_data("ele time.ods",data4)

def u_my_test2(net,topo):
 # create iperf and python server
    collect_mice_time=[]
    collect_ele_num=[]
    collect_mice_num=[]
    collect_ele_time=[]

    for i in xrange(0,16):
        net.get(topo.HostList[i]).cmdPrint('iperf -s -p 40000 -u > server_report/server_report_h' + str(i+1) + ' &')

   
    for i in xrange(0,16):
        (net.get(topo.HostList[i])).cmdPrint('python -m SimpleHTTPServer &')
   
    s=time.time()

   
    def generate_mice_flow(ele_time):
        t=4
        j=4



        print('start mice thread')

        while j > 0:
            global num_mice
            global num_ele
            time.sleep(4)
            j=j-1
 

            net.get(topo.HostList[4]).cmdPrint('wget 10.5.0.1:8000 -o mice_flow/mCT_h1' + '_' + str(round(time.time()-s)) + ' &')
           

            net.get(topo.HostList[5]).cmdPrint('wget 10.5.0.2:8000 -o mice_flow/mCT_h2' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[6]).cmdPrint('wget 10.6.0.1:8000 -o mice_flow/mCT_h3' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[7]).cmdPrint('wget 10.6.0.2:8000 -o mice_flow/mCT_h4' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[8]).cmdPrint('wget 10.7.0.1:8000 -o mice_flow/mCT_h5' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[9]).cmdPrint('wget 10.7.0.2:8000 -o mice_flow/mCT_h6' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[10]).cmdPrint('wget 10.8.0.1:8000 -o mice_flow/mCT_h7' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[11]).cmdPrint('wget 10.8.0.2:8000 -o mice_flow/mCT_h8' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[12]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h9' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[13]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h10' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[14]).cmdPrint('wget 10.2.0.1:8000 -o mice_flow/mCT_h11' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[15]).cmdPrint('wget 10.2.0.2:8000 -o mice_flow/mCT_h12' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[0]).cmdPrint('wget 10.3.0.1:8000 -o mice_flow/mCT_h13' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[1]).cmdPrint('wget 10.3.0.2:8000 -o mice_flow/mCT_h14' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[2]).cmdPrint('wget 10.4.0.1:8000 -o mice_flow/mCT_h15' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[3]).cmdPrint('wget 10.4.0.2:8000 -o mice_flow/mCT_h16' + '_' + str(round(time.time()-s)) + ' &')
    def generate_elephant_flow():
        global num_ele
        while time.time() - s < 300:
            logger.info('generate elephant flow')
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.3.0.1 -t 40 -p 40000 -i 1 -u > h1_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.3.0.1 -t 40 -p 40000 -i 1 -u > h1_report_'+ str(round(time.time()-s)) + ' &' )



            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.3.0.2 -t 40 -p 40000 -i 1 -u > h2_report_'+ str(round(time.time()-s)) + ' &' )
            #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.3.0.2 -t 40 -p 40000 -i 1 -u > h2_report_'+ str(round(time.time()-s)) + ' &' )


            net.get(topo.HostList[2]).cmdPrint('iperf -c 10.4.0.1 -t 40 -p 40000 -i 1 -u > h3_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[2]).cmdPrint('iperf -c 10.4.0.1 -t 40 -p 40000 -i 1 -u > h3_report_'+ str(round(time.time()-s)) + ' &' )


            net.get(topo.HostList[3]).cmdPrint('iperf -c 10.4.0.2 -t 40 -p 40000 -i 1 -u > h4_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[3]).cmdPrint('iperf -c 10.4.0.2 -t 40 -p 40000 -i 1 -u > h4_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[4]).cmdPrint('iperf -c 10.5.0.1 -t 40 -p 40000 -i 1 -u > h5_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[4]).cmdPrint('iperf -c 10.5.0.1 -t 40 -p 40000 -i 1 -u > h5_report_'+ str(round(time.time()-s)) + ' &' )


            net.get(topo.HostList[5]).cmdPrint('iperf -c 10.5.0.2 -t 40 -p 40000 -i 1 -u > h6_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[5]).cmdPrint('iperf -c 10.5.0.2 -t 40 -p 40000 -i 1 -u > h6_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[6]).cmdPrint('iperf -c 10.6.0.1 -t 40 -p 40000 -i 1 -u > h7_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[6]).cmdPrint('iperf -c 10.6.0.1 -t 40 -p 40000 -i 1 -u > h7_report_'+ str(round(time.time()-s)) + ' &' )


            net.get(topo.HostList[7]).cmdPrint('iperf -c 10.6.0.2 -t 40 -p 40000 -i 1 -u > h8_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[7]).cmdPrint('iperf -c 10.6.0.2 -t 40 -p 40000 -i 1 -u > h8_report_'+ str(round(time.time()-s)) + ' &' )
            
            net.get(topo.HostList[8]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 -u > h9_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[8]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -i 1 -u > h9_report_'+ str(round(time.time()-s)) + ' &' )


            net.get(topo.HostList[9]).cmdPrint('iperf -c 10.7.0.2 -t 40 -p 40000 -i 1 -u > h10_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[9]).cmdPrint('iperf -c 10.7.0.2 -t 40 -p 40000 -i 1 -u > h10_report_'+ str(round(time.time()-s)) + ' &' )
            
            net.get(topo.HostList[10]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 -u > h11_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[10]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -i 1 -u > h11_report_'+ str(round(time.time()-s)) + ' &' )


            net.get(topo.HostList[11]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 -u > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[11]).cmdPrint('iperf -c 10.8.0.2 -t 40 -p 40000 -i 1 -u > h12_report_'+ str(round(time.time()-s)) + ' &' )
            
            net.get(topo.HostList[12]).cmdPrint('iperf -c 10.1.0.1 -t 40 -p 40000 -i 1 -u > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[12]).cmdPrint('iperf -c 10.1.0.1 -t 40 -p 40000 -i 1 -u > h12_report_'+ str(round(time.time()-s)) + ' &' )


            net.get(topo.HostList[13]).cmdPrint('iperf -c 10.1.0.2 -t 40 -p 40000 -i 1 -u > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[13]).cmdPrint('iperf -c 10.1.0.2 -t 40 -p 40000 -i 1 -u > h12_report_'+ str(round(time.time()-s)) + ' &' )
            
            net.get(topo.HostList[14]).cmdPrint('iperf -c 10.2.0.1 -t 40 -p 40000 -i 1 -u > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[14]).cmdPrint('iperf -c 10.2.0.1 -t 40 -p 40000 -i 1 -u > h12_report_'+ str(round(time.time()-s)) + ' &' )


            net.get(topo.HostList[15]).cmdPrint('iperf -c 10.2.0.2 -t 40 -p 40000 -i 1 -u > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[15]).cmdPrint('iperf -c 10.2.0.2 -t 40 -p 40000 -i 1 -u > h12_report_'+ str(round(time.time()-s)) + ' &' )
           
            generate_mice_flow(round(time.time()-s))
            #time.sleep(25)
     
    generate_elephant_flow()


def my_test3(net,topo):
 # create iperf and python server
    for i in xrange(0,16):
        net.get(topo.HostList[i]).cmdPrint('iperf -s -p 40000 > server_report/server_report_h' + str(i+1) + ' &')

   
    for i in xrange(0,16):
        (net.get(topo.HostList[i])).cmdPrint('python -m SimpleHTTPServer &')
   
    #cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.7.0.1,actions=output:"3001-eth2"'
    #cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.7.0.1,actions=output:"3001-eth2"'
    #cmd3='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.7.0.1,actions=output:"3002-eth2"'
    #cmd4='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,idle_timeout=2,priority=20,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.7.0.1,actions=output:"3002-eth2"'
    cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.3.0.1,tcp,tp_src=8000,actions=output:"3001-eth1"'
    cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.3.0.2,tcp,tp_src=8000,actions=output:"3001-eth1"'
    cmd3='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.4.0.1,tcp,tp_src=8000,actions=output:"3002-eth1"'
    cmd4='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.4.0.2,tcp,tp_src=8000,actions=output:"3002-eth1"'
    cmd5='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth3",nw_src=10.3.0.1,nw_dst=10.5.0.1,tcp,tp_src=8000,actions=output:"3003-eth1"'
    cmd6='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth4",nw_src=10.3.0.2,nw_dst=10.5.0.2,tcp,tp_src=8000,actions=output:"3003-eth1"'
    cmd7='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth3",nw_src=10.4.0.1,nw_dst=10.6.0.1,tcp,tp_src=8000,actions=output:"3004-eth1"'
    cmd8='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth4",nw_src=10.4.0.2,nw_dst=10.6.0.2,tcp,tp_src=8000,actions=output:"3004-eth1"'
    cmd9='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth3",nw_src=10.5.0.1,nw_dst=10.7.0.1,tcp,tp_src=8000,actions=output:"3005-eth1"'
    cmd10='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth4",nw_src=10.5.0.2,nw_dst=10.7.0.2,tcp,tp_src=8000,actions=output:"3005-eth1"'
    cmd11='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.1,tcp,tp_src=8000,actions=output:"3006-eth1"'
    cmd12='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth4",nw_src=10.6.0.2,nw_dst=10.8.0.2,tcp,tp_src=8000,actions=output:"3006-eth1"'
    cmd13='ovs-ofctl add-flow 3007 -O OpenFlow13 table=0,priority=50,ip,in_port="3007-eth3",nw_src=10.7.0.1,nw_dst=10.1.0.1,tcp,tp_src=8000,actions=output:"3007-eth1"'
    cmd14='ovs-ofctl add-flow 3007 -O OpenFlow13 table=0,priority=50,ip,in_port="3007-eth4",nw_src=10.7.0.2,nw_dst=10.1.0.2,tcp,tp_src=8000,actions=output:"3007-eth1"'
    cmd15='ovs-ofctl add-flow 3008 -O OpenFlow13 table=0,priority=50,ip,in_port="3008-eth3",nw_src=10.8.0.1,nw_dst=10.2.0.1,tcp,tp_src=8000,actions=output:"3008-eth1"'
    cmd16='ovs-ofctl add-flow 3008 -O OpenFlow13 table=0,priority=50,ip,in_port="3008-eth4",nw_src=10.8.0.2,nw_dst=10.2.0.2,tcp,tp_src=8000,actions=output:"3008-eth1"'
   # cmd3='ovs-ofctl add-flow 2001 -O OpenFlow13 table=0,priority=1000,ip,in_port="2001-eth3",nw_src=10.1.0.1,nw_dst=10.8.0.1,actions=output:"2001-eth1"'
   # #cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=1000,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.8.0.1,actions=output:"3001-eth1"'
   # #cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=1000,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.8.0.2,actions=output:"3001-eth1"'
    os.system(cmd)
    os.system(cmd2)
    os.system(cmd3)
    os.system(cmd4)
    os.system(cmd5)
    os.system(cmd6)
    os.system(cmd7)
    os.system(cmd8)
    os.system(cmd9)
    os.system(cmd10)
    os.system(cmd11)
    os.system(cmd12)
    os.system(cmd13)
    os.system(cmd14)
    os.system(cmd15)
    os.system(cmd16)
    s=time.time()

    cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.3.0.1,tcp,tp_dst=40000,actions=output:"3001-eth1"'
    cmd2='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,priority=50,ip,in_port="3001-eth4",nw_src=10.1.0.2,nw_dst=10.3.0.2,tcp,tp_dst=40000,actions=output:"3001-eth2"'
    cmd3='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.4.0.1,tcp,tp_dst=40000,actions=output:"3002-eth1"'
    cmd4='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,priority=50,ip,in_port="3002-eth4",nw_src=10.2.0.2,nw_dst=10.4.0.2,tcp,tp_dst=40000,actions=output:"3002-eth2"'
    cmd5='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth3",nw_src=10.3.0.1,nw_dst=10.5.0.1,tcp,tp_dst=40000,actions=output:"3003-eth1"'
    cmd6='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,priority=50,ip,in_port="3003-eth4",nw_src=10.3.0.2,nw_dst=10.5.0.2,tcp,tp_dst=40000,actions=output:"3003-eth2"'
    cmd7='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth3",nw_src=10.4.0.1,nw_dst=10.6.0.1,tcp,tp_dst=40000,actions=output:"3004-eth1"'
    cmd8='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,priority=50,ip,in_port="3004-eth4",nw_src=10.4.0.2,nw_dst=10.6.0.2,tcp,tp_dst=40000,actions=output:"3004-eth2"'
    cmd9='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth3",nw_src=10.5.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3005-eth1"'
    cmd10='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,priority=50,ip,in_port="3005-eth4",nw_src=10.5.0.2,nw_dst=10.7.0.2,tcp,tp_dst=40000,actions=output:"3005-eth2"'
    cmd11='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3006-eth1"'
    cmd12='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,priority=50,ip,in_port="3006-eth4",nw_src=10.6.0.2,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3006-eth2"'
    cmd13='ovs-ofctl add-flow 3007 -O OpenFlow13 table=0,priority=50,ip,in_port="3007-eth3",nw_src=10.7.0.1,nw_dst=10.1.0.1,tcp,tp_dst=40000,actions=output:"3007-eth1"'
    cmd14='ovs-ofctl add-flow 3007 -O OpenFlow13 table=0,priority=50,ip,in_port="3007-eth4",nw_src=10.7.0.2,nw_dst=10.1.0.2,tcp,tp_dst=40000,actions=output:"3007-eth2"'
    cmd15='ovs-ofctl add-flow 3008 -O OpenFlow13 table=0,priority=50,ip,in_port="3008-eth3",nw_src=10.8.0.1,nw_dst=10.2.0.1,tcp,tp_dst=40000,actions=output:"3008-eth1"'
    cmd16='ovs-ofctl add-flow 3008 -O OpenFlow13 table=0,priority=50,ip,in_port="3008-eth4",nw_src=10.8.0.2,nw_dst=10.2.0.2,tcp,tp_dst=40000,actions=output:"3008-eth2"'

    os.system(cmd)
    os.system(cmd2)
    os.system(cmd3)
    os.system(cmd4)
    os.system(cmd5)
    os.system(cmd6)
    os.system(cmd7)
    os.system(cmd8)
    os.system(cmd9)
    os.system(cmd10)
    os.system(cmd11)
    os.system(cmd12)
    os.system(cmd13)
    os.system(cmd14)
    os.system(cmd15)
    os.system(cmd16)
    
    #cmd='ovs-ofctl add-flow 2001 -O OpenFlow13 table=0,priority=50,ip,in_port="2001-eth3",nw_src=10.1.0.1,nw_dst=10.3.0.1,tcp,tp_dst=40000,actions=output:"2001-eth1"'
    #cmd2='ovs-ofctl add-flow 2001 -O OpenFlow13 table=0,priority=50,ip,in_port="2001-eth4",nw_src=10.1.0.2,nw_dst=10.3.0.2,tcp,tp_dst=40000,actions=output:"3001-eth1"'
    #cmd3='ovs-ofctl add-flow 2002 -O OpenFlow13 table=0,priority=50,ip,in_port="2002-eth3",nw_src=10.2.0.1,nw_dst=10.4.0.1,tcp,tp_dst=40000,actions=output:"3002-eth1"'
    #cmd4='ovs-ofctl add-flow 2002 -O OpenFlow13 table=0,priority=50,ip,in_port="2002-eth4",nw_src=10.2.0.2,nw_dst=10.4.0.2,tcp,tp_dst=40000,actions=output:"3002-eth1"'
    #cmd5='ovs-ofctl add-flow 2003 -O OpenFlow13 table=0,priority=50,ip,in_port="2003-eth3",nw_src=10.3.0.1,nw_dst=10.5.0.1,tcp,tp_dst=40000,actions=output:"3003-eth1"'
    #cmd6='ovs-ofctl add-flow 2003 -O OpenFlow13 table=0,priority=50,ip,in_port="2003-eth4",nw_src=10.3.0.2,nw_dst=10.5.0.2,tcp,tp_dst=40000,actions=output:"3003-eth1"'
    #cmd7='ovs-ofctl add-flow 2004 -O OpenFlow13 table=0,priority=50,ip,in_port="2004-eth3",nw_src=10.4.0.1,nw_dst=10.6.0.1,tcp,tp_dst=40000,actions=output:"3004-eth1"'
    #cmd8='ovs-ofctl add-flow 2004 -O OpenFlow13 table=0,priority=50,ip,in_port="2004-eth4",nw_src=10.4.0.2,nw_dst=10.6.0.2,tcp,tp_dst=40000,actions=output:"3004-eth1"'
    #cmd9='ovs-ofctl add-flow 2005 -O OpenFlow13 table=0,priority=50,ip,in_port="2005-eth3",nw_src=10.5.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3005-eth1"'
    #cmd10='ovs-ofctl add-flow 2005 -O OpenFlow13 table=0,priority=50,ip,in_port="2005-eth4",nw_src=10.5.0.2,nw_dst=10.7.0.2,tcp,tp_dst=40000,actions=output:"3005-eth1"'
    #cmd11='ovs-ofctl add-flow 2006 -O OpenFlow13 table=0,priority=50,ip,in_port="2006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3006-eth1"'
    #cmd12='ovs-ofctl add-flow 2006 -O OpenFlow13 table=0,priority=50,ip,in_port="2006-eth4",nw_src=10.6.0.2,nw_dst=10.8.0.2,tcp,tp_dst=40000,actions=output:"3006-eth1"'
    #cmd13='ovs-ofctl add-flow 2007 -O OpenFlow13 table=0,priority=50,ip,in_port="2007-eth3",nw_src=10.7.0.1,nw_dst=10.1.0.1,tcp,tp_dst=40000,actions=output:"3007-eth1"'
    #cmd14='ovs-ofctl add-flow 2007 -O OpenFlow13 table=0,priority=50,ip,in_port="2007-eth4",nw_src=10.7.0.2,nw_dst=10.1.0.2,tcp,tp_dst=40000,actions=output:"3007-eth1"'
    #cmd15='ovs-ofctl add-flow 2008 -O OpenFlow13 table=0,priority=50,ip,in_port="2008-eth3",nw_src=10.8.0.1,nw_dst=10.2.0.1,tcp,tp_dst=40000,actions=output:"3008-eth1"'
    #cmd16='ovs-ofctl add-flow 2008 -O OpenFlow13 table=0,priority=50,ip,in_port="2008-eth4",nw_src=10.8.0.2,nw_dst=10.2.0.2,tcp,tp_dst=40000,actions=output:"3008-eth1"'

    #os.system(cmd)
    #os.system(cmd2)
    #os.system(cmd3)
    #os.system(cmd4)
    #os.system(cmd5)
    #os.system(cmd6)
    #os.system(cmd7)
    #os.system(cmd8)
    #os.system(cmd9)
    #os.system(cmd10)
    #os.system(cmd11)
    #os.system(cmd12)
    #os.system(cmd13)
    #os.system(cmd14)
    #os.system(cmd15)
    #os.system(cmd16)

    cmd='ovs-ofctl add-flow 3001 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3001-eth3",nw_src=10.1.0.1,nw_dst=10.3.0.1,tcp,tp_dst=40000,actions=output:"3001-eth2"'
    cmd2='ovs-ofctl add-flow 3002 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3002-eth3",nw_src=10.2.0.1,nw_dst=10.4.0.1,tcp,tp_dst=40000,actions=output:"3002-eth2"'
    cmd3='ovs-ofctl add-flow 3003 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3003-eth3",nw_src=10.3.0.1,nw_dst=10.5.0.1,tcp,tp_dst=40000,actions=output:"3003-eth2"'
    cmd4='ovs-ofctl add-flow 3004 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3004-eth3",nw_src=10.4.0.1,nw_dst=10.6.0.1,tcp,tp_dst=40000,actions=output:"3004-eth2"'
    cmd5='ovs-ofctl add-flow 3005 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3005-eth3",nw_src=10.5.0.1,nw_dst=10.7.0.1,tcp,tp_dst=40000,actions=output:"3005-eth2"'
    cmd6='ovs-ofctl add-flow 3006 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3006-eth3",nw_src=10.6.0.1,nw_dst=10.8.0.1,tcp,tp_dst=40000,actions=output:"3006-eth2"'
    cmd7='ovs-ofctl add-flow 3007 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3007-eth3",nw_src=10.7.0.1,nw_dst=10.1.0.1,tcp,tp_dst=40000,actions=output:"3007-eth2"'
    cmd8='ovs-ofctl add-flow 3008 -O OpenFlow13 table=0,hard_timeout=2,priority=60,ip,in_port="3008-eth3",nw_src=10.8.0.1,nw_dst=10.2.0.1,tcp,tp_dst=40000,actions=output:"3008-eth2"'
   
    def generate_mice_flow():
        t=4
        j=3
        #time.sleep(15)
        #os.system(cmd)
        #os.system(cmd2)
        #os.system(cmd3)
        #os.system(cmd4)



        print('start mice thread')
        while j > 0:
            time.sleep(10)
            j=j-1
           # os.system(cmd)
           # os.system(cmd2)
           # os.system(cmd3)
           # os.system(cmd4)
           # os.system(cmd5)
           # os.system(cmd6)
           # os.system(cmd7)
           # os.system(cmd8)
 
            logger.info('generate mice flow')
            net.get(topo.HostList[4]).cmdPrint('wget 10.5.0.1:8000 -o mice_flow/mCT_h1' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[5]).cmdPrint('wget 10.5.0.2:8000 -o mice_flow/mCT_h2' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[6]).cmdPrint('wget 10.6.0.1:8000 -o mice_flow/mCT_h3' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[7]).cmdPrint('wget 10.6.0.2:8000 -o mice_flow/mCT_h4' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[8]).cmdPrint('wget 10.7.0.1:8000 -o mice_flow/mCT_h5' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[9]).cmdPrint('wget 10.7.0.2:8000 -o mice_flow/mCT_h6' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[10]).cmdPrint('wget 10.8.0.1:8000 -o mice_flow/mCT_h7' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[11]).cmdPrint('wget 10.8.0.2:8000 -o mice_flow/mCT_h8' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[12]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h9' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[13]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h10' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[14]).cmdPrint('wget 10.2.0.1:8000 -o mice_flow/mCT_h11' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[15]).cmdPrint('wget 10.2.0.2:8000 -o mice_flow/mCT_h12' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[0]).cmdPrint('wget 10.3.0.1:8000 -o mice_flow/mCT_h13' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[1]).cmdPrint('wget 10.3.0.2:8000 -o mice_flow/mCT_h14' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[2]).cmdPrint('wget 10.4.0.1:8000 -o mice_flow/mCT_h15' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[3]).cmdPrint('wget 10.4.0.2:8000 -o mice_flow/mCT_h16' + '_' + str(round(time.time()-s)) + ' &')

                    #while t > 0:
        #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.2 -n 200000 -l 200000 > h2_report_'+ str(round(time.time()-s)) + ' &')
        #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.2 -n 300000 > h2_report_'+ str(round(time.time()-s)) + ' &')
        #net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.2 -n 500000 > h2_report_'+ str(round(time.time()-s)) + ' &')

                #t=t-1
   # mice_thread=threading.Thread(target=generate_mice_flow)
   # mice_thread.start() 
   # net.get(topo.HostList[0]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h1_report &')
   # net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h2_report &')
   # net.get(topo.HostList[2]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h3_report &')
   # net.get(topo.HostList[3]).cmdPrint('iperf -c 10.8.0.1 -t 40 > h4_report &')
    def generate_elephant_flow():
        print('start ele thread')
        while time.time() - s < 300:
            logger.info('generate elephant flow')
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.3.0.1 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h1_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.3.0.2 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h2_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[2]).cmdPrint('iperf -c 10.4.0.1 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h3_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[3]).cmdPrint('iperf -c 10.4.0.2 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h4_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[4]).cmdPrint('iperf -c 10.5.0.1 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h5_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[5]).cmdPrint('iperf -c 10.5.0.2 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h6_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[6]).cmdPrint('iperf -c 10.6.0.1 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h7_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[7]).cmdPrint('iperf -c 10.6.0.2 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h8_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[8]).cmdPrint('iperf -c 10.7.0.1 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h9_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[9]).cmdPrint('iperf -c 10.7.0.2 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h10_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[10]).cmdPrint('iperf -c 10.8.0.1 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h11_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[11]).cmdPrint('iperf -c 10.8.0.2 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[12]).cmdPrint('iperf -c 10.1.0.1 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[13]).cmdPrint('iperf -c 10.1.0.2 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[14]).cmdPrint('iperf -c 10.2.0.1 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[15]).cmdPrint('iperf -c 10.2.0.2 -t ' + str(random.randint(40,60)) + ' -p 40000 -i 1 > h12_report_'+ str(round(time.time()-s)) + ' &' )

            #t=threading.Thread(target=generate_mice_flow)

            generate_mice_flow()
            time.sleep(5)
    
    generate_elephant_flow()
def md_test(net,topo):
    s=time.time()
    for i in xrange(0,16):
        if i == 2 or i == 3 or i == 9 or i == 15:
            pass
        net.get(topo.HostList[i]).cmdPrint('iperf -s -p 40000 > server_report/server_report_h' + str(i+1) + ' &')


    for i in xrange(0,16):
        (net.get(topo.HostList[i])).cmdPrint('python -m SimpleHTTPServer &')

    
    def generate_mice():
        j=4

        while j>0:
            time.sleep(5)
            j=j-1
            net.get(topo.HostList[4]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h5' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[6]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h7' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[8]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h9' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[10]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h11' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[12]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h13' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[14]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h15' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[5]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h6' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[7]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h8' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[11]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h12' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[13]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h14' + '_' + str(round(time.time()-s)) + ' &')
    def generate_elephant():
        while time.time() -s < 300:
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.3.0.1 -t 40 -p 40000 > h1_report_h5'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.4.0.1 -t 40 -p 40000 > h1_report_h7'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.5.0.1 -t 40 -p 40000 > h1_report_h9'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.6.0.1 -t 40 -p 40000 > h1_report_h11'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 > h1_report_h13'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 > h2_report_h15'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.3.0.2 -t 40 -p 40000 > h2_report_h6'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.4.0.2 -t 40 -p 40000 > h2_report_h8'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.6.0.2 -t 40 -p 40000 > h2_report_h12'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.7.0.2 -t 40 -p 40000 > h2_report_h14'+ str(round(time.time()-s)) + ' &' )
            
            generate_mice()
            time.sleep(25)
    generate_elephant()
def u_md_test(net,topo):
    s=time.time()
    for i in xrange(0,16):
        if i == 2 or i == 3 or i == 9 or i == 15:
            pass
        net.get(topo.HostList[i]).cmdPrint('iperf -s -p 40000 -u > server_report/server_report_h' + str(i+1) + ' &')


    for i in xrange(0,16):
        (net.get(topo.HostList[i])).cmdPrint('python -m SimpleHTTPServer &')

    
    def generate_mice():
        j=4

        while j>0:
            time.sleep(5)
            j=j-1
            net.get(topo.HostList[4]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h5' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[6]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h7' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[8]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h9' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[10]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h11' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[12]).cmdPrint('wget 10.1.0.1:8000 -o mice_flow/mCT_h13' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[14]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h15' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[5]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h6' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[7]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h8' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[11]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h12' + '_' + str(round(time.time()-s)) + ' &')
            net.get(topo.HostList[13]).cmdPrint('wget 10.1.0.2:8000 -o mice_flow/mCT_h14' + '_' + str(round(time.time()-s)) + ' &')
    def generate_elephant():
        while time.time() -s < 300:
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.3.0.1 -t 40 -p 40000 -u > h1_report_h5'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.3.0.1 -t 40 -p 40000 -u > h1_report_h5'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.4.0.1 -t 40 -p 40000 -u > h1_report_h7'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.4.0.1 -t 40 -p 40000 -u > h1_report_h7'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.5.0.1 -t 40 -p 40000 -u > h1_report_h9'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.5.0.1 -t 40 -p 40000 -u > h1_report_h9'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.6.0.1 -t 40 -p 40000 -u > h1_report_h11'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.6.0.1 -t 40 -p 40000 -u > h1_report_h11'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -u > h1_report_h13'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[0]).cmdPrint('iperf -c 10.7.0.1 -t 40 -p 40000 -u > h1_report_h13'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -u > h2_report_h15'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.8.0.1 -t 40 -p 40000 -u > h2_report_h15'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.3.0.2 -t 40 -p 40000 -u > h2_report_h6'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.3.0.2 -t 40 -p 40000 -u > h2_report_h6'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.4.0.2 -t 40 -p 40000 -u > h2_report_h8'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.4.0.2 -t 40 -p 40000 -u > h2_report_h8'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.6.0.2 -t 40 -p 40000 -u > h2_report_h12'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.6.0.2 -t 40 -p 40000 -u > h2_report_h12'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.7.0.2 -t 40 -p 40000 -u > h2_report_h14'+ str(round(time.time()-s)) + ' &' )
            net.get(topo.HostList[1]).cmdPrint('iperf -c 10.7.0.2 -t 40 -p 40000 -u > h2_report_h14'+ str(round(time.time()-s)) + ' &' )
            
            generate_mice()
            #time.sleep(25)
    generate_elephant()


def CT_Test(net,topo):
    h001,h002,h003,h005,h007,h009,h011,h013,h014,h015,h016=net.get(topo.HostList[0],topo.HostList[1],topo.HostList[2],topo.HostList[4],topo.HostList[6],topo.HostList[8],topo.HostList[10],topo.HostList[12],topo.HostList[13],topo.HostList[14],topo.HostList[15])
    
    
    #iperf server
    
    net.get(topo.HostList[12]).cmdPrint('iperf -s -p 40000 > server_report/server_report_h13 &')
    net.get(topo.HostList[14]).cmdPrint('iperf -s -p 40000 > server_report/server_report_h15 &')
    net.get(topo.HostList[15]).cmdPrint('iperf -s -p 40000 > server_report/server_report_h16 &')

    for i in xrange(0,12):
        (net.get(topo.HostList[i])).cmdPrint('python -m SimpleHTTPServer &')

    def ele_flow(i):
        print('start ele_flow '+ str(i))
        _t=random.randint(20,60)
        t=threading.Thread(target=mice_flow2,args=(i,50))
        t.setDaemon(True)
        t.start()
      #  (net.get(topo.HostList[i])).popen('iperf -c ' + h013.IP() + ' -t 50' + ' > eCT_h' + str(i+1) + '_' + str(round(time.time()-s)) + ' &',shell=True)
      #  (net.get(topo.HostList[i])).popen('iperf -c ' + h015.IP() + ' -t 50' + ' > eCT_h' + str(i+1) + '_' + str(round(time.time()-s)) + ' &',shell=True)
      #  (net.get(topo.HostList[i])).popen('iperf -c ' + h016.IP() + ' -t 50' + ' > eCT_h' + str(i+1) + '_' + str(round(time.time()-s)) + ' &',shell=True)
      #  if i < 4:
      #      #(net.get(topo.HostList[i])).popen('iperf -c ' + h013.IP() + ' -t 40' + ' > eCT_h' + str(i+1) + '_' + str(round(time.time()-s)),shell=True)
      #      (net.get(topo.HostList[i])).cmdPrint('iperf -c ' + h013.IP() + ' -t 40' + ' > eCT_h' + str(i+1) + '_' + str((round(time.time()-s))))
      #  if i < 4 and i % 2 != 0:
      #   #   mice_flow2(i)

      #  if i >= 4 and i<8:
      #      (net.get(topo.HostList[i])).popen('iperf -c ' + h015.IP() + ' -t 50' + ' > eCT_h' + str(i+1) + '_' + str(round(time.time()-s)),shell=True)
      #      #(net.get(topo.HostList[i])).cmdPrint('iperf -c ' + h015.IP() + ' -t 20' + ' > eCT_h' + str(i+1) + '_' + str(round(time.time()-s)))

      # # if 4 <= i and i < 8 and i % 2 != 0:
      #    #  mice_flow2(i)

      #  if 8 <= i < 12:    
      #      (net.get(topo.HostList[i])).popen('iperf -c ' + h016.IP() + ' -t 50' + ' > eCT_h' + str(i+1) + '_' + str(round(time.time()-s)),shell=True)
      #      #(net.get(topo.HostList[i])).cmdPrint('iperf -c ' + h016.IP() + ' -t 20' + ' > eCT_h' + str(i+1) + '_' + str(round(time.time()-s)))
      #    #  if 8 <= i < 12 and i % 2 != 0:
      #         # mice_flow2(i)
      #      #mice_flow2(i)
    def mice_flow2(i,t):
        #t=round(t / 10)
        t=1
        end = 0
        while t > 0:
            sleep_time=10
            if end > 0 and end <= 10:
                sleep_time= 10 - end
            if end > 10:
                sleep_time=0
            time.sleep(sleep_time)
            print('mice_flow2')
            t=t-1
            start=round(time.time())
            #(net.get(topo.HostList[i])).cmdPrint('iperf -c ' + h013.IP() + ' -n 10250' + ' -l 10250' + ' > mCT_h' + str(i+1) + '_' + str(round(time.time()-s)))
            #(net.get(topo.HostList[i])).cmdPrint('iperf -c ' + h015.IP() + ' -n 10250' + ' -l 10250' + ' > mCT_h' + str(i+1) + '_' + str(round(time.time()-s)))
            #(net.get(topo.HostList[i])).cmdPrint('iperf -c ' + h016.IP() + ' -n 10250' + ' -l 10250' + ' > mCT_h' + str(i+1) + '_' + str(round(time.time()-s)))
           # (net.get(topo.HostList[i])).cmdPrint('wget "' + h013.IP() + ':8000" ' + '-o mice_flow/mCT_h' + str(i+1) + '_' + str(round(time.time()-s)))
           # (net.get(topo.HostList[i])).cmdPrint('wget "' + h015.IP() + ':8000" ' + '-o mice_flow/mCT_h' + str(i+1) + '_' + str(round(time.time()-s)))
           # (net.get(topo.HostList[i])).cmdPrint('wget "' + h016.IP() + ':8000" ' + '-o mice_flow/mCT_h' + str(i+1) + '_' + str(round(time.time()-s)))

            h016.cmdPrint('wget "' + (net.get(topo.HostList[i])).IP() + ':8000" ' + '-o mice_flow/mCT_h' + str(i+1) + '_' + str(round(time.time()-s)) + ' &')
            h015.cmdPrint('wget "' + (net.get(topo.HostList[i])).IP() + ':8000" ' + '-o mice_flow/mCT_h' + str(i+1) + '_' + str(round(time.time()-s)) + ' &')
            h013.cmdPrint('wget "' + (net.get(topo.HostList[i])).IP() + ':8000" ' + '-o mice_flow/mCT_h' + str(i+1) + '_' + str(round(time.time()-s)) + ' &')
           # if i < 4:
           #     (net.get(topo.HostList[i])).cmdPrint('wget "' + h013.IP() + ':8000" ' + '-o mCT_h' + str(i+1) + '_' + str(round(time.time()-s)))
           #     #(net.get(topo.HostList[i])).cmdPrint('iperf -c ' + h015.IP() + ' -n 10250' + ' -l 10250' + ' -r' + ' > mCT_h' + str(i+1) + '_' + str(round(time.time()-s)))

           # if 4 <= i < 8:
           #     (net.get(topo.HostList[i])).cmdPrint('wget "' + h015.IP() + ':8000" ' + '-o mCT_h' + str(i+1) + '_' + str(round(time.time()-s)))
           # if 8 <= i < 12:
           #     (net.get(topo.HostList[i])).cmdPrint('wget "' + h016.IP() + ':8000" ' + '-o mCT_h' + str(i+1) + '_' + str(round(time.time()-s)))
            #end=round(time.time()-start)
    def T_ele_flow(i):
        t=threading.Thread(target=T_mice_flow,args=(i,40))
        #t.setDaemon(True)
        #t.start()
        #time.sleep(40)
        (net.get(topo.HostList[i])).popen('iperf -c ' + h013.IP() + ' -t 40' + ' > eCT_h' + str(i+1) + '_' + str((round(time.time()-s))),shell=True )
    def T_mice_flow(i,t):
        t=round(t / 10)
        end=0
        while t > 0:
            sleep_time=10
            if end > 0 and end <= 10:
                sleep_time = 10 - end
            if end > 10 :
                sleep_time=0
            print('sleep',sleep_time)
            time.sleep(sleep_time)
            t=t-1
            start=round(time.time())
            (net.get(topo.HostList[i])).cmdPrint('iperf -c ' + h013.IP() + ' -n 10000' + ' > mCT_h' + str(i+1) + '_' + str(round(time.time()-s)))
            end=round(time.time()-start)
            print('mice FCT',end)
    def generate_mice_flow():
        local_threads=[]
        for i in xrange(12):
            t=threading.Thread(target=mice_flow2,args=(i,))
            local_threads.append(t)
        for thread in local_threads:
            thread.setDaemon(True)
            thread.start()
        for thread in local_threads:
            thread.join()
    
    def generate_ele_flow():
        local_threads=[]
        for i in xrange(1):
            t=threading.Thread(target=ele_flow,args=(i,))
            local_threads.append(t)
        for thread in local_threads:
            thread.start()
        for thread in local_threads:
            thread.join()

    s=time.time()
    thread=[]
    for i in xrange(0,12):
        t=threading.Thread(target=ele_flow,args=(i,))
        thread.append(t)
        thread[i].start()
    time.sleep(50)
    #while time.time() - s < 300:    
    #generate_ele_flow()
  #      for i in xrange(12):
  #          if i < 4:
  #              p=(net.get(topo.HostList[i])).popen('iperf -c ' + h013.IP() + ' -t 20' + ' > eCT_h' + str(i+1) + '_' + str(time.time()-s),shell=True)
  #              process.append(p)
  #          if 4 <= i < 8:
  #              p=(net.get(topo.HostList[i])).popen('iperf -c ' + h015.IP() + ' -t 20' + ' > eCT_h' + str(i+1) + '_' + str(time.time()-s),shell=True)
  #              process.append(p)
  #          if 8 <= i < 12:
  #              p=(net.get(topo.HostList[i])).popen('iperf -c ' + h016.IP() + ' -t 20' + ' > eCT_h' + str(i+1) + '_' + str(time.time()-s),shell=True)
  #              process.append(p)
  #      time.sleep(20)
  #  for i in xrange(12):
  #      process[i].kill()
    #UT
    #iperf server

    #iperf client

    ##MD
    ##iperf server
    #for i in xrange(4,13):
    #    (net.get(topo.HostList[k])).popen("iperf -s &")
    #
    ##iperf client
    #for i in xrange(4,13):
    #    h001.cmdPrint('iperf -c ' +(net.get(topo.HostList[i])).IP() +' -t 10 -i 1') 
    #    h002.cmdPrint('iperf -c ' +(net.get(topo.HostList[i])).IP() +' -t 10 -i 1')


def run_experiment(pod, density, ip="127.0.0.1", port=6653, bw_c2a=10, bw_a2e=10, bw_e2h=10):
	"""
		Create the network topology. Then, define the connection with the remote controller.
		Install the proactive flow entries, set IPs and OF version.
		Finally, run the Sieve as a module inside RYU controller, and wait until it discovers the network,
		then, we generate different traffic patterns based on command line arguments passed.
	"""
	# Create Topo.
	topo = Fattree(pod, density)
	topo.createNodes()
	topo.createLinks(bw_c2a=bw_c2a, bw_a2e=bw_a2e, bw_e2h=bw_e2h)

	# 1. Start Mininet.
	CONTROLLER_IP = ip
	CONTROLLER_PORT = port
	net = Mininet(topo=topo, link=TCLink, controller=None, autoSetMacs=True)
	net.addController(
		'controller', controller=RemoteController,
		ip=CONTROLLER_IP, port=CONTROLLER_PORT)
	net.start()

	# Set the OpenFlow version for switches as 1.3.0.
	topo.set_ovs_protocol_13()
	# Set the IP addresses for hosts.
	set_host_ip(net, topo)
	# Install proactive flow entries.
	install_proactive(net, topo)
	#print topo.HostList[0]
	
	k_paths = 4 ** 2 * 3 / 4
	fanout = 4
	#Controller_Ryu = Popen("ryu-manager --observe-links sieve.py --k_paths=%d --weight=bw --fanout=%d" % (k_paths, fanout), shell=True, preexec_fn=os.setsid)

	# Wait until the controller has discovered network topology.
	time.sleep(60)
        
	#choose one from ct,ut,md to start experiment
        UT_Test(net,topo)
        #CT_Test(net,topo)
        #md_test(net,topo)
	
        
	
        CLI(net)
	#os.killpg(Controller_Ryu.pid, signal.SIGKILL)
	# Stop Mininet.
	net.stop()

if __name__ == '__main__':
	setLogLevel('info')
	if os.getuid() != 0:
		logging.warning("You are NOT root!")
	elif os.getuid() == 0:
		run_experiment(4, 2)
