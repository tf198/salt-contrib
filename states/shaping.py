'''
Traffic Shaping using tc

Creates executable scripts to enforce traffic shaping on an interface from
a tree-type data structure.  Takes care of generating the identifiers and flow
control so you can focus on the behavior.

This has only been tested with PRIO, SFQ and HTB qdiscs, it should work for others
but some of them have little quirks - please let me know when you find them.

There is no standard way to manage this so we just create a `/etc/tc_shaping_<iface>` executable
that configures shaping on the interface.  You should add an appropriate entry to your network configuration
to call the file e.g on Debian based systems add an `up /etc/tc_shaping_eth0` entry to `/etc/network/interfaces`.
Changes to managed interfaces are applied automatically without needing to restart the network interface.

The following data structures are available
..

  qdisc: { type: <prio,sfq,htb,...>, __options__: <qdisc options>, __classes__: [<class>, ...], __comment__: <comment> }
  class: { options: <class options>, __classes__: [<class>, ...], __filters__: [<filter>, ...], __comment__: <comment>, __id__: <override auto id> }
  filter: <u32 filter string>

.. code-block:: yaml

  eth0: # basic priority queue - see http://www.lartc.org/howto/lartc.qdisc.classful.html#AEN902
    shaping.qdisc:
      - type: prio
      - classes:
        - qdisc: { type: sfq } # prio 1
        - qdisc: { type: tbf, options: rate 20kbit buffer 1600 limit 3000 } # prio 2
        - qdisc: { type: sfq } # prio 3

  eth1: # More complicated Hierarchical Token Bucket example
    shaping.qdisc:
      - type: htb
      - default: 13
      - classes:
        - comment: Interface limit
          options: rate 1024kbit # slightly below the connection speed
          classes:
            - comment: Default traffic
              id: 13                                    # explicit class ID so we can reference as default from the qdisc
              options: rate 768kbit ceil 1024kbit prio 2
              qdisc: { type: sfq, options: perturb 10 } # recommended to always add a SFQ to the bottom of everything
            - comment: Interactive traffic
              filters: [ match ip tos 0x10 0xff ]       # TOS interactive
              options: rate 128kbit prio 1
              qdisc: { type: sfq, options: perturb 10 }
            - comment: Bulk traffic
              filters: [ match: ip tos 0x08 0xff ]       # TOS bulk
              options: rate 128kbit ceil 1024kbit prio 3
              qdisc: { type: sfq, options: perturb 10 }
                
'''

import difflib

def qdisc(name, script=None, apply=True , **qdisc):
    '''
    Set up traffic shaping for the named interface

    interface
        The name of the interface to shape

    qdisc
        The root qdisc specification, as above
    '''
    ret = {
        'name': name,
        'changes': {},
        'result': True,
        'comment': 'Shaping for interface {0} is up to date.'.format(name)
    }
    
    # Build interface
    try:
        old = __salt__['tc.get_script'](name, script)
        new = __salt__['tc.build_script'](name, qdisc, script)
        
        if not old and new:
            ret['changes']['shaping'] = 'Created shaping script.'
        elif old != new:
            diff = difflib.unified_diff(old, new)
            ret['changes']['shaping'] = ''.join(diff)
        else:
            return ret # no changes
        
    except AttributeError as error:
        ret['result'] = False
        ret['comment'] = error.message
        return ret
    
    enable = qdisc.get('enabled', True)
    
    if not apply:
        ret['comment'] = "Skipping apply tc script <enabled={0}>.".format(enable)
        return ret
    
    try:
        if enable:
            __salt__['tc.enable'](name, script)
            ret['comment'] = "Shaping enabled for interface {0}.".format(name)
        else:
            __salt__['tc.disable'](name)
            ret['comment'] = "Shaping disabled for interface {0}.".format(name)
    except Exception as error:
        ret['result'] = False
        ret['comment'] = error.message
        return ret
    
    return ret