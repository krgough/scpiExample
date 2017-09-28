'''
Created on 2 Dec 2016

@author: keith

scpi Module for communication with LAN connected instruments
tested with Keysight 34465a multimeter

'''
import time
import socket
from tqdm import tqdm

HOST='10.19.2.5'
PORT=5025
debug=True

class scpi(object):
    def __init__(self,HOST,PORT):
        self.buffersize=256
        self.socketTimeout=10
        self.error = None
        
        self.sock=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.socketTimeout)
        try:
            self.sock.connect((HOST,PORT))
        except socket.error as e:
            self.error="ERROR: Socket connection error. {}".format(e)
            self.sock=None
    def write(self,payload):
        # Must have a newline char
        payload=(payload + '\n').encode()
        try:
            self.sock.send(payload)
            self.error=None
            return True
        except socket.error as e:
            self.error="ERROR: Socket send error. {}".format(e)
            return False
    def read(self):
        respState=False
        respValue=None
        try:
            respValue=self.sock.recv(self.buffersize)
            self.error=None
            respState=True
        except socket.error as e:
            self.error="ERROR: socket recieve error. {}".format(e)
            respValue=None
            respState=False
        return respState,respValue
    def close(self):
        self.sock.close()
        return
    
def getValue(scpiObject,payload):
    """ Generic handler code for getting a value from the instrument
    
    """
    if not scpiObject.write(payload):
        respState=False
        respValue=None
    else:
        respState,respValue=scpiObject.read()
    return respState,respValue
def getIDN(scpiObject):
    """ Send *IDN? to get instrument identifier
    
    """
    return getValue(scpiObject,'*IDN?')
def getConf(scpiObject):
    """ CONF?
    
        Returns a quoted string indicating the present function, range, and resolution.
        The short form of the function name (CURR:AC, FREQ) is always returned.
    
    """
    return getValue(scpiObject,'CONF?')
def getLabel(scpiObject):
    """ SYSTem:LABel?
    
        Places a message in a large font on the bottom half of the instrument's front panel display.
        
    """
    return getValue(scpiObject,'SYSTem:LABel?')
def getMeasCurr(scpiObject,mAcDc,mRange,mRes):
    """ MEASure:CURRent:{AC|DC}? [{<range>|AUTO|MIN|MAX|DEF} [, {<resolution>|MIN|MAX|DEF}]]
        
        Sets all measurement parameters and trigger parameters to their default values for AC or DC
        current measurements and immediately triggers a measurement. The results are sent directly
         to the instrument's output buffer.
         
    """
    payload = "MEAS:CURR:{} {},{}".format(mAcDc,mRange,mRes)
    return getValue(scpiObject,payload)
def getFormatData(scpiObject):
    """ FORMat[:DATA]?
        Returns the data format: either ASCII or REAL.
        
    """
    payload = "FORMat:DATA?"
    return getValue(scpiObject,payload)
def getError(scpiObject):
    """ SYSTem:ERRor?
    
    
    """
    payload="SYSTem:ERRor?"
    return getValue(scpiObject,payload)

def setValue(scpiObject,payload):
    """ Generic handler code for setting a value on the instrument
    
    """
    if not scpiObject.write(payload):
        respState=False
    else:
        respState=True
    return respState
def setBeep(scpiObject):
    """ SYSTem:BEEPer
    
        Issues a single beep.
        
    """
    return setValue(scpiObject,"SYST:BEEP")
def setConfCurr(scpiObject,mAcDc,mRange,mRes):
    """ CONFigure:CURRent:{AC|DC} [{<range>|AUTO|MIN|MAX|DEF} [, {<resolution>|MIN|MAX|DEF}]]
        Sets all measurement parameters and trigger parameters to their default values for AC or DC current
        measurements. Also specifies the range and resolution.
        
    """
    payload="CONF:CURR:{} {},{}".format(mAcDc,mRange,mRes)
    return setValue(scpiObject,payload)
def setLabel(scpiObject,payload):
    """ SYST:LAB "<string>"
    
        Places a message in a large font on the bottom half of the instrument's front panel display.
        Max 40chars
        
    """
    payload = 'SYST:LAB "{}"'.format(payload)
    return setValue(scpiObject,payload)
def setDisplayState(scpiObject,onOffState):
    """ DISPlay[:STATe] {ON|1|OFF|0}
    
        Disables or enables the front panel display. When disabled, the display dims,
        and all annunciators are disabled. However, the screen remains on.
    
    """
    payload = "DISP:STAT {}".format(onOffState)
    return setValue(scpiObject,payload)
def setReset(scpiObject):
    """ *RST
    
        Resets instrument to factory default state. This is similar to SYSTem:PRESet. The difference
        is that *RST resets the instrument for SCPI operation, and SYSTem:PRESet resets the instrument
        for front panel operation. As a result, *RST turns the histogram and statistics off,
        and SYSTem:PRESet turns them on.
        
    """
    payload="*RST"
    return setValue(scpiObject,payload)
def setAbort(scpiObject):
    """ ABORt
    
        Aborts a measurement in progress, returning the instrument to the trigger idle state.
        
    """
    payload="ABORt"
    return setValue(scpiObject,payload)

def getHandler(scpiObject,myMethod,*args):
    """
    """
    respState,respValue=myMethod(scpiObject,*args)
    if not respState:
        print(scpiObject.error)
        exit()
    else:
        return respState,respValue 
def setHandler(scpiObject,myMethod,*args):
    """
    """
    respState=myMethod(scpiObject,*args)
    if not respState:
        print(scpiObject.error)
        exit()
    else:
        return(respState)

def parseBlockHeader(block):
    """ Takes a byte string with a definiteLength header
        Returns the dataStart position, numExpectedBytes, numActualBytes
        #512345<data>
    
    """
    try:
        numDigits=int(block[1:2])
        dataStart=numDigits+2
        numExpectedBytes=int(block[2:dataStart])
        if block[-1:]==b'\n':
            numActualBytes=len(block[dataStart:-1])
        else:
            numActualBytes=len(block[dataStart: ])
    except:
        print(block)
        exit()
    return dataStart,numExpectedBytes,numActualBytes
def readData(scpiObject,filename,expectedPoints,progress=True):
    """ Read data using *R? command and save it to a file.
        Returns True if no errors.
        
        expectedPoints is the number of expected samples in the set
       
        read first block
        parse expected size & actual size
        loop until actual=expected
        
        extract final dataset and add it to data list
        
    """
    data=[]
    
    blockSize=10000
    buffLen=(blockSize*16)+256
    
    # Setup the progress bar
    if progress: pbar = tqdm(total=expectedPoints)
    
    while len(data)<expectedPoints:
        if setValue(scpiObject,'R? {}'.format(buffLen)):

            block=scpiObject.sock.recv(buffLen)
            while not block.endswith(b'\n'):
                block=block + scpiObject.sock.recv(buffLen)
            
            dataStart,numExpectedBytes,numActualBytes=parseBlockHeader(block)
            #print(numExpectedBytes,numActualBytes)
            
            if numExpectedBytes!=numActualBytes:
                print('Byte count error')
                exit()
                
            if numExpectedBytes!=0:
                blockList=block.decode().strip()[dataStart:].split(',')
                data=data+blockList
                if progress: pbar.update(len(blockList))
                            
        else:
            return False
        time.sleep(1)
    
    with open(filename,'w') as f:
        for dp in data:
            f.write("{}\n".format(dp))
    return True

def screenDump(scpiObject,filename):
    """ HCOPy:SDUMp:DATA?
    
        Response is a file png or bmp delivered as bytes in an
        IEEE 488.2 definite-length block.

        A typical data block using the definite length format consists of:
        
        Start of data block
        | Number of digits in digits
        | |               Number of data bytes to be sent
        | |               |          Data bytes
        | |               |          |  
        #<Non zero digit><len chars><file bytes>
        
        A typical example of a data block sending 2000 8-bit data bytes is:
        #42000<data bytes>
    
    """
    if setValue(meter,"HCOPy:SDUMp:DATA?"):
        buff=meter.sock.recv(256)
        
        # strip the header out
        numDigits=int(chr(buff[1]))
        fileSize=int(buff[2:numDigits+2])        
        buff=buff[2+numDigits:]

        # Now grab the rest from the socket
        while len(buff)<fileSize:
            buff=buff+meter.sock.recv(256)
        
        with open(filename,'wb') as f:    
            # Remove the final '\n'
            f.write(buff[0:-1])
    else:
        return False
    return True

def currentMeasureSetup(meter,currRange='10mA',apperture=0.001,numSamples=1000000,sampleRate=0.001,debug=False):
    """ Method to send the setup commands
    
    """
    # Configure the instrument to take the readings
    settings=['SENS:FUNC:ON "CURR:DC"',
              'CONF:CURR:DC {}'.format(currRange),
              'SENS:CURR:DC:ZERO:AUTO OFF',
              'SENS:CURR:DC:APER {}'.format(apperture),
              'SAMP:COUNT {}'.format(numSamples),
              'TRIG:SOUR BUS',
              'SAMP:SOUR TIM',
              'SAMP:TIM {}'.format(sampleRate),
              'INIT']
    
    for s in settings:
        setValue(meter,s)
        error=getHandler(meter,getError)[1].decode().split(',')[1].strip()
        if error!='"No error"':
            print("***ERROR: {},{}".format(s,error))
            exit()
        if debug:
            print(s,'No error')
    return
def logCurrent(scpiObject,filename,currRange='10mA',apperture='1E-03',numSamples=1000000,sampleRate=0.001,debug=False):
    """  Logs current using given parameters.  Defaults are..
        
        Range                 = 10mA range
        Integration apperture = 1E-03 (1ms)
        numSamples            = 1000000
        sampleRate            = 1E-03 (1ms)
        
        Results are saved to a file.
    
    """
    # Initial config - Reset instrument and DIM the display
    if debug: print('Resetting the multimeter...')
    setHandler(meter, setDisplayState,'OFF')
    setHandler(meter, setReset)
    
    # Setup for the measurement
    currentMeasureSetup(scpiObject, currRange, apperture, numSamples, sampleRate, debug)
    
    # Trigger the instrument
    setValue(meter,'*TRG')
    
    #screenDump(meter, '/tmp/junk.png')    
    if debug: print("\nWaiting for measurement to complete: {} samples requested".format(numSamples))
    readData(meter, filename, numSamples)
    
    return

def currentMultiRun(scpiObject,filename,currRange='10mA',apperture='1E-03',numSamples=1000000,sampleRate=0.001,debug=False):
    """
    """
    currentMeasureSetup(scpiObject, currRange, apperture, numSamples, sampleRate, debug)
    filename='/tmp/junk1.txt'
    
    print("{:22},{:8},{:22},{:22}".format("Average","Count","Min","Max"))
    for _ in range(1):
        setValue(scpiObject,"*TRG")
        readData(scpiObject, filename, numSamples, progress=True)
        results = calcStats(filename)
        print("{}".format(results['average'],results['count'],results['min'],results['max']))

def calcStats(filename):
    """
    """
    data=[]
    with open(filename,'r') as f:
        for line in f:
            data.append(float(line.strip()))
     
    av=sum(data)/len(data)

    results={}
    results['average'] = av
    results['count'] = len(data)
    results['min'] = min(data)
    results['max'] = max(data)

    return results

if __name__=="__main__":
    
    meter=scpi(HOST,PORT)
    if meter.sock==None:
        print("No socket. Exit. {}".format(meter.error))
        exit()
    else:
        if debug: print(getHandler(meter,getIDN))
        
    """ Screen dump """ 
    #setValue(meter,"DISP:STAT on")
    #screenDump(meter, '/tmp/junk.png') 
    mins=60
    sampleRate=1
    currRange='100mA'
    aperture=sampleRate
    numSamples = mins*60/sampleRate 
    filename='/tmp/junk1.txt'
    
    logCurrent(meter, filename,
               numSamples=numSamples,
               apperture=aperture,
               sampleRate=sampleRate,
               currRange='100mA',
               debug=True)
    
    #currentMultiRun(meter, '/tmp/junk1.txt')
    
    meter.close()
    
    print('All done')