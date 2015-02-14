from ArmoryUtils import *
import ReedSolomonWrapper


################################################################################
class WalletEntry(object):
   """
   The wallets will be made up of IFF/RIFF entries. 


   The REQUIRED_TYPES list is all the wallet entry codes that MUST be 
   understood by the reading application in order to move forward 
   reading and using the wallet.  If a data type is in the list, a flag
   will be set in the serialization telling the application that it 
   should throw an error if it does not recognize it.

   Example 1 -- Colored Coins (not implemented yet):
      If a given wallet handles colored coins, it could be a disaster
      if the application did not recognize that, and let you spend 
      your colored coins as if they were regular BTC.  Thefore, if you
      are going to implement colored coins, you must add that code to
      the REQUIRED_TYPES list.  Then, if vanilla Armory (without colored
      coin support) is used to read the wallet, it will not allow the 
      user to use that wallet
         
   Example 2 -- P2SH Scripts:
      This is borderline, and I may add this to the REQUIRED_TYPES list
      as I get further into implementation.  Strictly speaking, you don't
      *need* P2SH information in order to use the non-P2SH information 
      in the wallet (such as single sig addresses), but you won't 
      recognize much of the BTC that is [partially] available to that 
      wallet if you don't read P2SH scripts.
   

   The following comments are for labels & P2SH scripts:

   The goal of this object type is to allow for generic encryption to 
   be applied to wallet entries without regard for what data it is.

   Our root private key only needs to be backed up once, but all of the 
   P2SH scripts should be backed up regularly (and comment fields would be 
   nice to have backed up, too).  The problem is, you don't want to put 
   your whole wallet file into dropbox, encrypted or not.  The solution is
   to have a separate P2SH&Comments file (a wallet without any addresses)
   which can be put in Dropbox.

   The solution is to have a file that can be put in dropbox, and each
   entry is AES encrypted using the 32 bytes of the PUBLIC FINGERPRINT as
   the encryption key.   This allows you to decrypt this entry without 
   even unlocking your wallet, but it does require you to have that (WO)
   wallet in your possession.  Your wallet should NOT be backed up this
   way, thus anyone gaining access to only the P2SH&Comment file would NOT
   have the information needed to decrypt it (and by using the finger-
   print of the address, they can't simply try every public key in the 
   blockchain ... they must have access to at least the watching-only wlt).
  
   """
   # Any classes that inherit from WalletEntry that want WalletEntry to be
   # able to spawn objects of its type when found in a wallet file, needs
   # to call RegisterWalletStorageClass.  Technically, we could get around
   # this using reflection, but reading direct class names out of wallet
   # files and invoking them feels as dangerous like using eval()
   FILECODEMAP    = {}
   REQUIRED_TYPES = set()
   KEYPAIR_TYPES  = set()
   RSEC_FUNCS = {'Create': ReedSolomonWrapper.createRSECCode,
                 'Check':  ReedSolomonWrapper.checkRSECCode}


   #############################################################################
   @staticmethod
   def RegisterWalletStorageClass(clsType, isReqd=False):
      weCode = clsType.FILECODE
      if weCode in WalletEntry.FILECODEMAP:
         raise ValueError('Class with code "%s" is already in map!' % weCode)

      WalletEntry.FILECODEMAP[clsType.FILECODE] = clsType
      if isReqd:
         WalletEntry.REQUIRED_TYPES.add(weCode)

      try:
         from ArmoryKeyPair import ArmoryKeyPair
         if issubclass(clsType, ArmoryKeyPair):
            WalletEntry.KEYPAIR_TYPES.add(weCode)
            LOGINFO('Registered %s class as a keypair type')
      except:
         LOGERROR('Failed to check if class is keypair type: %s' % clsType.__name__)
         # This is when ArmoryKeyPair hasn't been defined yet.  That's fine.
         pass

   #############################################################################
   @staticmethod
   def ChangeRSECAlgos(createFunc, checkFunc):
      """
      This is mainly for testing purposes.  See DisableRSEC(...) for an example 
      calling this function.  You could even change the algos to some other 
      error correction scheme, but you'll need to make sure it uses the 1024/16
      ratio.

      One reason we might want to disable RSEC is that we have a wallet file 
      which was created "manually" and the user didn't have a library for 
      creating the RSEC codes.  
      """
      WalletEntry.RSEC_FUNCS['Create'] = createFunc
      WalletEntry.RSEC_FUNCS['Check']  = checkFunc


   #############################################################################
   @staticmethod
   def CreateRSECCode(*args, **kwargs):
      return WalletEntry.RSEC_FUNCS['Create'](*args, **kwargs)

   #############################################################################
   @staticmethod
   def CheckRSECCode(*args, **kwargs):
      return WalletEntry.RSEC_FUNCS['Check'](*args, **kwargs)

   #############################################################################
   @staticmethod
   def DisableRSEC():
      def checkfn(data, parity):
         return data, False, False
         
      def createfn(data, rsecBytes=ReedSolomonWrapper.RSEC_PARITY_BYTES, 
                         perDataBytes=ReedSolomonWrapper.RSEC_PER_DATA_BYTES):
         nChunk = (len(data)-1)/perDataBytes + 1
         return '\x00' * rsecBytes * nChunk

      WalletEntry.ChangeRSECAlgos(createfn, checkfn)
   
         

   #############################################################################
   def __init__(self, wltFileRef=None, offset=None, weSize=None, reqdBit=False,    
                      parEntryID=None, outerCrypt=None, ekeyRef=None, 
                      serPayload=None, defaultPad=256):

      # TODO:  Why on earth is this needed here...?  
      from ArmoryEncryption import ArmoryCryptInfo
      self.wltFileRef = wltFileRef
      self.wltByteLoc = offset
      self.wltEntrySz = weSize
      self.isRequired = reqdBit
      self.parEntryID = parEntryID
      self.outerCrypt = outerCrypt.copy() if outerCrypt else ArmoryCryptInfo(None)
      self.serPayload = serPayload
      self.defaultPad = defaultPad

      self.wltParentRef = None
      self.wltChildRefs = []
      self.outerEkeyRef = None
      #self.wltEntryID = None
      #self.flagBitset = BitSet(16)

      self.isOpaque = False
      self.isOrphan = False
      self.isUnrecognized = False
      self.isUnrecoverable = False
      self.isDeleted = False
      self.isDisabled = False
      self.needFsync = False


   #############################################################################
   def copyFromWE(self, weOther):
      self.wltFileRef = weOther.wltFileRef
      self.wltByteLoc = weOther.wltByteLoc
      self.wltEntrySz = weOther.wltEntrySz
      self.isRequired = weOther.isRequired
      self.parEntryID = weOther.parEntryID
      self.outerCrypt = weOther.outerCrypt.copy()
      self.serPayload = weOther.serPayload
      self.defaultPad = weOther.defaultPad

      self.wltParentRef = weOther.wltParentRef
      self.wltChildRefs = weOther.wltChildRefs[:]
      self.outerEkeyRef = weOther.outerEkeyRef
      
         
   #############################################################################
   @staticmethod
   def CreateDeletedEntry(weSize, wltFileRef=None, wltOffset=None):
      we = WalletEntry()
      we.isDeleted = True
      we.wltEntrySz = weSize
      we.wltFileRef = wltFileRef
      we.wltOffset  = wltOffset
      return we
      
   #############################################################################
   def getEntryID(self):
      raise NotImplementedError('This must be overriden by derived class!')


   #############################################################################
   def linkWalletEntries(self, wltFileRef):
      # All parents will be ArmorySeededKeyPair objects
      self.wltFileRef = wltFileRef
      parent = wltFileRef.masterScrAddrMap.get(self.parEntryID)
      if parent is None:
         self.isOrphan = True
         wltFileRef.wltParentMissing.append(self)
         return

      self.wltParentRef = parent
      if not parent==self:
         parent.wltChildRefs.append(self)


   #############################################################################
   def serializeEntry(self, doDelete=False, **encryptKwargs):

      weFlags = BitSet(16)
      if self.isDeleted or doDelete:
         weFlags.setBit(0, True)
         nZero = self.wltEntrySz - 10  # version(4) + flags(2) + numZero(4)
         
         bp = BinaryPacker()
         bp.put(UINT32,       getVersionInt(ARMORY_WALLET_VERSION)) 
         bp.put(BITSET,       weFlags, 2)
         bp.put(UINT32,       nZero)
         bp.put(BINARY_CHUNK, '\x00'*nZero)
         return bp.getBinaryString()
         
         
      # Going to create the sub-serialized object that might be encrypted
      serObject = self.serialize()
      lenObject = len(serObject)

      plBits = BitSet(16)
      plBits.setBit(0, self.FILECODE in WalletEntry.REQUIRED_TYPES)

      bpPayload = BinaryPacker() 
      bpPayload.put(BINARY_CHUNK, self.FILECODE, width=8) 
      bpPayload.put(BITSET,       plBits, 2)
      bpPayload.put(VAR_STR,      self.getEntryID())
      bpPayload.put(VAR_STR,      serObject)

      # Now we have the full unencrypted version of the data for the file
      serPayload = padString(bpPayload.getBinaryString(), self.defaultPad)
       
      if self.outerCrypt.useEncryption():
         raise NotImplementedError('Outer encryption not yet implemented!')
         if not len(serPayload) % self.outerCrypt.getBlockSize() == 0:
            raise EncryptionError('Improper padding on payload data for encryption')
         serPayload = self.outerCrypt.encrypt(serPayload, **encryptKwargs)

      # Computes 16-byte Reed-Solomon error-correction code per 1024 bytes
      rsecCode = WalletEntry.CreateRSECCode(serPayload)

      # Now we have everything we need to serialize the wallet entry
      bp = BinaryPacker()
      bp.put(UINT32,       getVersionInt(ARMORY_WALLET_VERSION)) 
      bp.put(BITSET,       weFlags, 2)
      bp.put(VAR_STR,      self.parEntryID)
      bp.put(BINARY_CHUNK, self.outerCrypt.serialize(),  width=32)
      bp.put(VAR_STR,      serPayload)
      bp.put(VAR_STR,      rsecCode)
      return bp.getBinaryString()
      

   #############################################################################
   @staticmethod
   def UnserializeEntry(toUnpack, parentWlt, fOffset, **decryptKwargs):
      """
      Unserialize a WalletEntry object -- the output of this function is
      actually a class derived from WalletEntry:  it uses the 8-byte FILECODE
      [static] member to determine what class's unserialize method should be
      used on the "payload"

      The flow is a little awkward:  we make a generic WalletEntry object that 
      will be updated with generic data and some booleans, but it will only be
      used if we have to return early due to urecoverable, unrecognized or 
      undecryptable.  Otherwise, at the end we make and return a new object
      of the correct class type, and set all the members on it that were set
      on the "we" object earlier
      """
      # TODO: Need to fix the circ ref issues that are requiring these imports
      from ArmoryEncryption import ArmoryCryptInfo

      we = WalletEntry()
      we.wltFileRef = parentWlt
      we.wltByteLoc = fOffset 

      toUnpack = makeBinaryUnpacker(toUnpack)
      unpackStart  = toUnpack.getPosition()

      wltVersion   = toUnpack.get(UINT32)
      weFlags      = toUnpack.get(BITSET, 2)  # one byte

      if wltVersion != getVersionInt(ARMORY_WALLET_VERSION):
         LOGWARN('WalletEntry version: %s,  Armory Wallet version: %s', 
                     getVersionString(readVersionInt(wltVersion)), 
                     getVersionString(ARMORY_WALLET_VERSION))


      we.isDeleted = weFlags.getBit(0)

      if we.isDeleted:
         # Don't use VAR_INT/VAR_SIZE for size of zero chunk due to complixty 
         # of handling the size being at the boundary of two VAR_INT sizes
         # 10 == version(4) + flags(2) + numZero(4)
         we.wltEntrySz = toUnpack.get(UINT32) + 10
         shouldBeZeros = toUnpack.get(BINARY_CHUNK, we.wltEntrySz - 10)
         if not len(shouldBeZeros)==shouldBeZeros.count('\x00'):
            raise UnserializeError('Deleted entry is not all zero bytes')
         return we


      parEntryID    = toUnpack.get(VAR_STR)
      serCryptInfo  = toUnpack.get(BINARY_CHUNK, 32)  
      serPayload    = toUnpack.get(VAR_STR)  
      rsecCode      = toUnpack.get(VAR_STR)


      we.parEntryID   = parEntryID
      we.wltEntrySz   = toUnpack.getPosition() - unpackStart
      we.payloadSz    = len(serPayload)

      we.isOpaque        = False
      we.isUnrecognized  = False
      we.isUnrecoverable = False

      # Detect and correct any bad bytes in the data
      we.serPayload,fail,mod = WalletEntry.CheckRSECCode(serPayload, rsecCode)
      if fail:
         LOGERROR('Unrecoverable error in wallet entry')
         we.isUnrecoverable = True 
         return we
      elif mod:
         LOGWARN('Error in wallet file corrected successfully')
         we.needFsync = True 


      we.outerCrypt = ArmoryCryptInfo().unserialize(serCryptInfo)

      if we.outerCrypt.noEncryption():
         # Parse payload
         return we.parsePayloadReturnNewObj()
      else:
         we.isOpaque  = True
         if len(decryptKwargs)==0:
            return we
         else:
            # Decrypt-then-parse payload
            return we.decryptPayloadReturnNewObj(**decryptKwargs)


   #############################################################################
   def parsePayloadReturnNewObj(self):

      if self.isOpaque:
         raise EncryptionError('Payload of WltEntry is encrypted.  Cannot parse')

      # The following is all the data that is inside the payload, which is
      # all hidden/opaque if it's encrypted
      buPayload = BinaryUnpacker(self.serPayload)
      plType  = buPayload.get(BINARY_CHUNK, 8)
      plFlags = buPayload.get(BITSET, 2)
      plObjID = buPayload.get(VAR_STR)
      plData  = buPayload.get(VAR_STR)

      # Throw an error if padding consists of more than \x00... don't want
      # it to become a vessel for transporting/hiding data (like Windows ADS)
      nBytesLeft = buPayload.getRemainingSize()
      leftover = buPayload.getRemainingString()
      if leftover.count('\x00') < nBytesLeft:
         raise EncryptionError('Padding in wlt entry is non-zero!')


      # The first bit tells us that if we don't understand this wallet entry,
      # we shouldn't use this wallet (perhaps this wallet manages colored coins
      # and was loaded on vanilla Armory -- we don't want to spend those coins.
      self.isRequired = plFlags.getBit(0)

      # Use the 8-byte FILECODE to determine the type of object to unserialize
      clsType = WalletEntry.FILECODEMAP.get(plType)
      if clsType is None:
         LOGWARN('Unrecognized data type in wallet: "%s"' % plType)
         self.isUnrecognized = True
         return self

      # Return value is actually a subclass of WalletEntry
      weOut = WalletEntry.FILECODEMAP[plType]().unserialize(plData)
      weOut.copyFromWE(self)
      weOut.needFsync = self.needFsync or weOut.needFsync
      # (subclass might've triggered rewrite flag, don't want to overwrite it)

      if not weOut.getEntryID() == plObjID:
         raise UnserializeError('Stored obj ID does not match computed')

      return weOut


   #############################################################################
   def decryptPayloadReturnNewObj(self, **outerCryptArgs):
      if not self.isOpaque:
         raise EncryptionError('Payload data is not encrypted!')

      try:
         cryptPL = SecureBinaryData(self.serPayload)
         plainPL = self.outerCrypt.decrypt(cryptPL, **outerCryptArgs)
         self.serPayload = plainPL.toBinStr()
         self.isOpaque = False
         return self.parsePayloadReturnNewObj()
      except:
         LOGEXCEPT('Decryption of WalletEntry payload failed')
      



   #############################################################################
   def getEkeyFromWallet(self, ekeyID):
      if self.wltFileRef is None:
         raise WalletExistsError('This wallet entry has no wallet file!')

      return self.wltFileRef.ekeyMap.get(ekeyID, None)



   #############################################################################
   def fsync(self):
      if self.wltFileRef is None:
         LOGERROR('Attempted to rewrite WE object but no wlt file ref.')
         return

      if self.wltByteLoc<=0:
         self.wltFileRef.doFileOperation('AddEntry', self)
      else:
         self.wltFileRef.doFileOperation('UpdateEntry', self)

   #############################################################################
   def queueFsync(self):
      if self.wltFileRef is None:
         LOGERROR('Attempted to rewrite WE object but no wlt file ref.')
         return

      if self.wltByteLoc is None or self.wltByteLoc<=0:
         self.wltFileRef.addFileOperationToQueue('AddEntry', self)
      else:
         self.wltFileRef.addFileOperationToQueue('UpdateEntry', self)


   #############################################################################
   def useOuterEncryption(self):
      return outerCrypt.useEncryption()

        
   #############################################################################
   def disableAllWltChildren(self):
      self.isDisabled = True
      for child in self.wltChildRefs:
         child.disableAllWltChildren()   
         

   #############################################################################
   def removeOuterEncryption(self, oldKey, oldIV=None):
      raise NotImplementedError


   #############################################################################
   #def pprintOneLine(self, nIndent=0):
      #fmtField = lambda lbl,val,wid: '(%s %s)'%(lbl,str(val)[:wid].rjust(wid))
      #print fmtField('', self.FILECODE, 8),
      #print fmtField('in', self.self.wltFileRef.filepath.basename(), 4),


from ArmoryEncryption import *

try:
   from ArmoryKeyPair import *
except:
   LOGERROR('Could not import ArmoryKeyPair module')


