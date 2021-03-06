#!/usr/bin/env python2

def create_network(paths, bw, loss, latency):
    from mininet.net import Mininet
    from mininet.link import TCLink
    from mininet.node import CPULimitedHost, Controller
    from mininet.log import info

    net = Mininet(controller=Controller, link=TCLink)

    # since we need a switch we also need a controller
    c0 = net.addController('c0')
    s1 = net.addSwitch('s1')

    # create virtual hosts
    h1 = net.addHost('h1', cpu=40)
    h2 = net.addHost('h2', cpu=40)

    info("Create link s1 <-> h2 ")
    li = net.addLink(s1, h2)
    info("\n")

    info("Create link h1 <-> s1 ")
    li = net.addLink(h1, s1, loss=loss, bw=bw, delay=latency)
    info("\n")

    # create the links
    for i in range(paths-1):
        info("Create link h1 <-> s1 ")
        li = net.addLink(h1, s1, loss=loss, bw=bw, delay=latency)
        li.intf1.setIP("192.168.%d.1"%i, 24)
        info("\n")

    return net

def set_route(intf, gateway, table):
    intf.cmd("ip rule add from %s table %d" % (intf.ip, table), shell=True)
    shift = 32-int(intf.prefixLen)
    netnum = reduce(lambda l, r: (l<<8) + int(r), intf.ip.split("."), 0) >> shift << shift
    netip = ".".join([str((netnum>>(24-i*8))&0xff) for i in range(4)])
    intf.cmd("ip route add %s/%s dev %s scope link table %d" % (netip, intf.prefixLen, intf.name, table), shell=True)
    intf.cmd("ip route add default dev %s table %d" % (intf.name, table), shell=True)

def sysctl(name, value):
    from subprocess import check_output
    return check_output(["sysctl", "-w", str(name) + "=" + str(value)])

def set_parameter(name, value):
    from subprocess import check_output
    with open (name, "w") as subf:
        subf.write(str(value))
    return name + " = " + check_output(["cat", name])

def setup(net):
    h1 = net["h1"]
    h2 = net["h2"]

    for i in h1.intfs:
        h1.intfs[i].ifconfig("down")
    sleep(1)

    for i in h1.intfs:
        intf1 = h1.intfs[i]

        intf1.ifconfig("up")
        intf1.cmd("ip link set dev %s multipath on", intf1.name)
        set_route(intf1, h2.intfs[0].ip, i+1)

        if i == 0:
            h1.cmd("ip route add default scope global nexthop via %s dev %s" % (h2.intfs[0].ip, intf1.name), shell=True)

    sys.stderr.write("h1: ip rule show\n" + h1.cmdPrint("ip rule show"))
    sys.stderr.write("h1: ip route\n" + h1.cmdPrint("ip route"))

    for i in h1.intfs:
        sys.stderr.write(("h1: ip route show table %d\n"%(i+1)) + h1.cmdPrint("ip route show table %d" % (i+1)))

    h2.cmd("ip route add default dev %s" % h2.defaultIntf().name)

    sys.stderr.write("h2: ip rule show\n" + h2.cmdPrint("ip rule show"))
    sys.stderr.write("h2: ip route\n" + h2.cmdPrint("ip route"))

    for i in h2.intfs:
        sys.stderr.write(("h2: ip route show table %d\n"%(i+1)) + h2.cmdPrint("ip route show table %d" % (i+1)))

def start_bwm(node, filename=None):
    from mininet.term import makeTerm

    cmd = ["bwm-ng", "-u", "bits"]
    if filename:
        return node.popen(cmd + ["-o", "csv", "-F", filename, "-T", "sum"])
    else:
        makeTerm(node, cmd="bash -c '%s || read'"% " ".join(cmd))
        return None

def start_htop(node):
    from mininet.term import makeTerm

    cmd = ["htop"]
    makeTerm(node, cmd="bash -c '%s || read'"% " ".join(cmd))

def start_tcpdump(node):
    return node.popen(["tcpdump", "-i", "any", "-s", "65535", "-w", node.name+".pcap"])

def pingall(*nodes):
    for s in nodes:
        for d in nodes:
            if s == d:
                continue
            for i in s.intfs:
                for j in d.intfs:
                    sys.stderr.write(s.cmdPrint(["ping", "-I", s.intfs[i].name, "-c", "4", d.intfs[j].ip]))

if __name__ == '__main__':
    from time import sleep
    import sys
    import argparse

    parser = argparse.ArgumentParser("Setup a Multipath environment and run a benchmark")
    parser.add_argument("--term", action='store_true',
            help="Run the tunnel in xterm. This makes the stdout of nctun visible")
    parser.add_argument("--cli", action='store_true',
            help="Run the mininet CLI instead of the benchmark")
    parser.add_argument("--bwm", default=None,
            help="Run a bandwidth monitor on the switch and save to a csv file")
    parser.add_argument("--bwm-term", action='store_true',
            help="Run a bandwidth monitor on the nodes")
    parser.add_argument("--htop", action='store_true',
            help="Run a htop on the nodes")
    parser.add_argument("--tcpdump", action='store_true',
            help="Use tcpdump to store the transfered packets")
    parser.add_argument("--log", default=None,
            help="Set the mininet log level")
    parser.add_argument("--bw", default=1, type=float,
            help="Bandwidth in Mbps for each path")
    parser.add_argument("--paths", default=2, type=int,
            help="Maximum number of paths between the nodes")
    parser.add_argument("--loss", default=0, type=int,
            help="Loss percentage for each link")
    parser.add_argument("--latency", default="10ms",
            help="Latency of a single packet transmission")
    parser.add_argument("--time", type=int, default=10,
            help="Duration of the benchmark")
    parser.add_argument("--repeat", type=int, default=1,
            help="Number of times to repeat one measurement")
    parser.add_argument("--mptcp-disabled", action='store_true',
            help="Disable the kernel mptcp support")
    parser.add_argument("--mptcp-syn-retries", type=int, default=3,
            help="""Specifies how often we retransmit a SYN with the
            MP_CAPABLE-option. After this, the SYN will not contain the
            MP_CAPABLE-option. This is to handle middleboxes that drop SYNs
            with unknown TCP options.""")
    parser.add_argument("--mptcp-no-checksum", action='store_true', default=False,
            help="Disable the MPTCP checksum")
    parser.add_argument("--mptcp-path-manager", default="fullmesh",
            help="Select the MPTCP path manager")
    parser.add_argument("--mptcp-subflows", default=1,
            help="Number of subflows to use")
    parser.add_argument("--congestion-control", default="olia",
            help="Congestion control algorithm")

    args = parser.parse_args()

    # set the log level to get some feedback from mininet
    if args.log:
        from mininet.log import setLogLevel
        setLogLevel(args.log)

    if args.mptcp_disabled:
        sys.stderr.write(sysctl("net.mptcp.mptcp_enabled", 0))
    else:
        sys.stderr.write(sysctl("net.mptcp.mptcp_enabled", 1))
        sys.stderr.write(sysctl("net.mptcp.mptcp_syn_retries", args.mptcp_syn_retries))
        if args.mptcp_no_checksum:
            sys.stderr.write(sysctl("net.mptcp.mptcp_checksum", 0))
        else:
            sys.stderr.write(sysctl("net.mptcp.mptcp_checksum", 1))
        sys.stderr.write(sysctl("net.mptcp.mptcp_path_manager", args.mptcp_path_manager))
        sys.stderr.write(sysctl("net.ipv4.tcp_congestion_control", args.congestion_control))

        sys.stderr.write(set_parameter("/sys/module/mptcp_%s/parameters/num_subflows" % args.mptcp_path_manager, args.mptcp_subflows))

    net = create_network(paths=args.paths, bw=args.bw, loss=args.loss, latency=args.latency)
    net.start()

    s1 = net['s1']
    h1 = net['h1']
    h2 = net['h2']

    sleep(1)
    setup(net)
    pingall(h1, h2)

    procs = []

    if args.bwm:
        procs.append(start_bwm(s1, args.bwm))

    if args.bwm_term:
        start_bwm(h1)
        start_bwm(h2)

    if args.htop:
        start_htop(h1)
        start_htop(h2)

    if args.tcpdump:
        procs.append(start_tcpdump(h1))
        procs.append(start_tcpdump(h2))

    sleep(2)

    if args.cli:
        from mininet.cli import CLI
        CLI(net)
    else:
        for _ in range(args.repeat):
            sleep(1)
            result = net.iperf(seconds=args.time, fmt="m")
            print "%s %s" % (result[0], result[1])

    for p in procs:
        if p:
            p.terminate()
            p.wait()

    net.stop()

