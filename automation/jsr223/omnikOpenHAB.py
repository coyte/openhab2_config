"""OmnikOpenHAB program.

Get data from an Omnik inverter with 602xxxxx - 606xxxx ans save the data in
OpenHAB items.
"""



scriptExtension.importPreset("RuleSupport")
scriptExtension.importPreset("RuleSimple")


from org.slf4j import LoggerFactory
import socket  # Needed for talking to inverter
import sys
import ConfigParser
import os
import struct  # Converting bytes to numbers

class OmnikOpenhab(object):
    """
    Get data from Omniksol inverter and store the data in OpenHAB items.
    """
    global logger
    logger = LoggerFactory.getLogger("org.eclipse.smarthome.model.script.rules")
 
    def __init__(self, config_file):
        #logger.info("omnikOPENHAB - Starting")
        # Load the settings
        path = "/etc/openhab2/automation/jsr223/"
        config_files = path+config_file
        self.config = ConfigParser.RawConfigParser()
        self.config.read(config_files)

    def getInverters(self):
        #Get number of inverters
        inverterCount = len(self.config.sections())-2
        #logger.info("omnikOPENHAB - Invertercount: {0}".format(inverterCount))
        #Reset totals to zero
        OmnikOpenhab.total_e_today = 0
        OmnikOpenhab.total_e_total = 0
        OmnikOpenhab.total_p_ac = 0
        #For each inverter, get data and add to total
        for i in range(1,inverterCount+1):
            #logger.info("omnikOPENHAB - In the inverterloop, value of index: {0}".format(i))
            msg = self.run(i)
            #logger.info("omnikOPENHAB - Value of msg is {0}".format(msg))
            #Assume daytime (for processing data)
            day=1
            # If retrieved data is not a InverterMsg object: No updates
            #if 'timed' in format(msg):
            if isinstance(msg,InverterMsg):
                #logger.info("omnikOPENHAB - Day time -- valid data") 
                self.add(msg)
            else:    
                day=0
                #logger.info("omnikOPENHAB - Timed out - BREAKING")
                break   
            
            
    
        #Only process durig day time
        if day:
            etotal = self.config.get('openhab_items', 'etotal')
            etoday = self.config.get('openhab_items', 'etoday')
            epower = self.config.get('openhab_items', 'epower')
            logger.info("omnikOPENHAB - Items updated: {0}: {1}, {2}: {3}, {4}: {5}, ".format(etotal,OmnikOpenhab.total_e_total,etoday,OmnikOpenhab.total_e_today,epower,OmnikOpenhab.total_p_ac))
            events.postUpdate(str(etotal), str(OmnikOpenhab.total_e_total))
            events.postUpdate(str(etoday), str(OmnikOpenhab.total_e_today))
            events.postUpdate(str(epower), str(OmnikOpenhab.total_p_ac))
        else:
            logger.info("omnikOPENHAB - No data (after sunset?), not updating database")

        #logger.info("omnikOPENHAB - End")
  




    def add(self,msg):
        #logger.info("omnikOPENHAB - Adding data")
        OmnikOpenhab.total_e_today += msg.e_today
        OmnikOpenhab.total_e_total += msg.e_total
        OmnikOpenhab.total_p_ac += msg.p_ac(1) + msg.p_ac(2) + msg.p_ac(3)

        

    def run(self,inverternr):
        """Get information from inverter and store is configured outputs."""
        # Connect to inverter
        msg=''
        ip = self.config.get('inverter' + str(inverternr), 'ip')
        port = self.config.get('inverter' + str(inverternr), 'port')
        for res in socket.getaddrinfo(ip, port, socket.AF_INET, socket.SOCK_STREAM):
            family, socktype, proto, canonname, sockadress = res
            try:
                #logger.info("omnikOPENHAB - connecting to {0} port {1}".format(ip, port))
                inverter_socket = socket.socket(family, socktype, proto)
                inverter_socket.settimeout(10)
                inverter_socket.connect(sockadress)
                #logger.info("omnikOPENHAB - Retrieved data..")
            except socket.error as msg:
                return(msg)
                #logger.info("omnikOPENHAB - Could not connect to inverter.")
            wifi_serial = self.config.getint('inverter' + str(inverternr), 'wifi_sn')
            inverter_socket.sendall(OmnikOpenhab.generate_string(wifi_serial))
            data = inverter_socket.recv(1024)
            inverter_socket.close()
            msg = InverterMsg(data)
        return(msg)

    def override_config(self, section, option, value):
        """Override config settings"""
        self.config.set(section, option, value)

    @staticmethod
    def generate_string(serial_no):
        """Create request string for inverter.

        The request string is build from several parts. The first part is a
        fixed 4 char string; the second part is the reversed hex notation of
        the s/n twice; then again a fixed string of two chars; a checksum of
        the double s/n with an offset; and finally a fixed ending char.

        Args:
            serial_no (int): Serial number of the inverter

        Returns:
            str: Information request string for inverter
        """
        response = '\x68\x02\x40\x30'
        double_hex = hex(serial_no)[2:] * 2
        hex_list = [double_hex[i:i + 2].decode('hex') for i in
                    reversed(range(0, len(double_hex), 2))]
        cs_count = 115 + sum([ord(c) for c in hex_list])
        checksum = hex(cs_count)[-2:].decode('hex')
        response += ''.join(hex_list) + '\x01\x00' + checksum + '\x16'
        return response

class InverterMsg(object):
    """Decode the response message from an omniksol inverter."""
    raw_msg = ""

    def __init__(self, msg, offset=0):
        self.raw_msg = msg
        self.offset = offset

    def __get_string(self, begin, end):
        """Extract string from message.

        Args:
            begin (int): starting byte index of string
            end (int): end byte index of string

        Returns:
            str: String in the message from start to end
        """
        return self.raw_msg[begin:end]

    def __get_short(self, begin, divider=10):
        """Extract short from message.

        The shorts in the message could actually be a decimal number. This is
        done by storing the number multiplied in the message. So by dividing
        the short the original decimal number can be retrieved.

        Args:
            begin (int): index of short in message
            divider (int): divider to change short to float. (Default: 10)

        Returns:
            int or float: Value stored at location `begin`
        """
        num = struct.unpack('!H', self.raw_msg[begin:begin + 2])[0]
        if num == 65535:
            return -1
        else:
            return float(num) / divider

    def __get_long(self, begin, divider=10):
        """Extract long from message.

        The longs in the message could actually be a decimal number. By
        dividing the long, the original decimal number can be extracted.

        Args:
            begin (int): index of long in message
            divider (int): divider to change long to float. (Default : 10)

        Returns:
            int or float: Value stored at location `begin`
        """
        return float(
            struct.unpack('!I', self.raw_msg[begin:begin + 4])[0]) / divider

    @property
    def id(self):
        """ID of the inverter."""
        return self.__get_string(15, 31)

    @property
    def temperature(self):
        """Temperature recorded by the inverter."""
        return self.__get_short(31)

    @property
    def power(self):
        """Power output"""
        print self.__get_short(59)

    @property
    def e_total(self):
        """Total energy generated by inverter in kWh"""
        return self.__get_long(71)

    def v_pv(self, i=1):
        """Voltage of PV input channel.

        Available channels are 1, 2 or 3; if not in this range the function will
        default to channel 1.

        Args:
            i (int): input channel (valid values: 1, 2, 3)

        Returns:
            float: PV voltage of channel i
        """
        if i not in range(1, 4):
            i = 1
        num = 33 + (i - 1) * 2
        return self.__get_short(num)

    def i_pv(self, i=1):
        """Current of PV input channel.

        Available channels are 1, 2 or 3; if not in this range the function will
        default to channel 1.

        Args:
            i (int): input channel (valid values: 1, 2, 3)

        Returns:
            float: PV current of channel i
        """
        if i not in range(1, 4):
            i = 1
        num = 39 + (i - 1) * 2
        return self.__get_short(num)

    def i_ac(self, i=1):
        """Current of the Inverter output channel

        Available channels are 1, 2 or 3; if not in this range the function will
        default to channel 1.

        Args:
            i (int): output channel (valid values: 1, 2, 3)

        Returns:
            float: AC current of channel i

        """
        if i not in range(1, 4):
            i = 1
        num = 45 + (i - 1) * 2
        return self.__get_short(num)

    def v_ac(self, i=1):
        """Voltage of the Inverter output channel

        Available channels are 1, 2 or 3; if not in this range the function will
        default to channel 1.

        Args:
            i (int): output channel (valid values: 1, 2, 3)

        Returns:
            float: AC voltage of channel i
        """
        if i not in range(1, 4):
            i = 1
        num = 51 + (i - 1) * 2
        return self.__get_short(num)

    def f_ac(self, i=1):
        """Frequency of the output channel

        Available channels are 1, 2 or 3; if not in this range the function will
        default to channel 1.

        Args:
            i (int): output channel (valid values: 1, 2, 3)

        Returns:
            float: AC frequency of channel i
        """
        if i not in range(1, 4):
            i = 1
        num = 57 + (i - 1) * 4
        return self.__get_short(num, 100)

    def p_ac(self, i=1):
        """Power output of the output channel

        Available channels are 1, 2 or 3; if no tin this range the function will
        default to channel 1.

        Args:
            i (int): output channel (valid values: 1, 2, 3)

        Returns:
            float: Power output of channel i
        """
        if i not in range(1, 4):
            i = 1
        num = 59 + (i - 1) * 4
        return int(self.__get_short(num, 1))  # Don't divide

    @property
    def e_today(self):
        """Energy generated by inverter today in kWh"""
        return self.__get_short(69, 100)  # Divide by 100

    @property
    def h_total(self):
        """Hours the inverter generated electricity"""
        return int(self.__get_long(75, 1))  # Don't divide


class myRule(SimpleRule):
    def execute(self, module, inputs):
        omnik_openhab = OmnikOpenhab('omnikOpenHAB.cfg')
        omnik_openhab.getInverters()

#Housekeeping below
omnik = myRule()
omnik.setTriggers([Trigger("aTimerTrigger", "timer.GenericCronTrigger", Configuration({"cronExpression": "0 * * * * ?"}))])

'''
#Code block below enables triggerin of the rule by an item update, in this case the switch item 'ruleTrigger'
omnik.triggers = [
             Trigger("MyTrigger", "core.ItemStateUpdateTrigger", 
                    Configuration({ "itemName": "ruleTrigger"}))
        ]
'''
automationManager.addRule(omnik)
