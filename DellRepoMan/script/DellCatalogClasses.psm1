# Dell Catalog PS module

Class DellSystem {
	[string] $Name
	[string] $Nickname
	[string] $Agile
	[System.XML.XMLElement]  $TargetSystems
	[System.XML.XMLElement]  $TargetOSes
	[Hashtable[]] $Packages
	[int] $SizeBytes
	[string]$DateStamp

	DellSystem([System.XML.XMLElement]$SystemNode) {
		write-verbose "DellSystem:  Constructing object for name $($systemnode.Name)"
		$this.Name = $SystemNode.Name
		$this.NickName = $SystemNode.NickName
		$this.Agile = $SystemNode.Agile
		$this.TargetSystems = $SystemNode.SelectSingleNode("TargetSystems")
		$this.TargetOSes = $SystemNode.SelectSingleNode("TargetOSes")
		# derive target OS
		
		# collect packages
		
		$this.Packages = @()
		foreach ($pkgnode in $SystemNode.GetElementsByTagName("Package")) {
			$pkg = @{}
			$pkg.path = $pkgnode.path
			$pkg.Folder = $pkgnode.Folder
            $pkg.version = $pkgnode.version
            if (-not $pkg.version) {
                $pkg.version = "1"
            }
			$this.Packages += $pkg
		}
		$this.DateStamp = (Get-Date -format 'yyyy-MM-ddTHH:mm:ss') + (Get-timezone).BaseUtcOffset.ToString().Substring(0,6)
	}

	# utility method to generate the ubiquitous <Display "lang"="en"> </Display> structures
	[System.XML.XMLElement] MakeLangDisplayElement([System.XML.XMLDocument]$doc, [string]$TagName, [string]$Text) {
		write-verbose "DellSystem:  Generating Display XML for tag $tagname with innertext '$Text'"
		[System.XML.XMLElement]$elem = $doc.CreateElement($TagName)
		$display = $doc.CreateElement('Display')
		$display.SetAttribute('lang','en')
		$display.InnerText = $Text
		$elem.AppendChild($display)
		
		return $elem
	}
	

	# Create the SoftwareBundle node and structure, return as XMLElement
	# targetOS must be one of 'LIN', 'WIN64', 'WIN'
	[System.XML.XMLElement] GetSWBundle([System.XML.XMLDocument]$xmldoc, [string]$TargetOS = 'LIN') {
		write-verbose "DellSystem:  Generating SoftwareBundle XML for System named $($this.Name) for TargetOS $TargetOS"
		$pathOS = 'XX'
		$btype = 'BTXX'
		$displayOS = 'Unknown'
		
		switch ($TargetOS) {
			'LIN' {
				$pathOS = 'LX'
				$btype = 'BTLX'
				$displayOS = 'Linux'
				
			}
			'WIN64' {
				$pathOS = 'WIN64'
				$btype = 'BTW64'
				$displayOS = 'Windows x64'
			}
			'WIN' {
				$pathOS = 'WIN'
				$btype = 'BTW32'
				$displayOS = 'Windows'
			}
			default {
				throw "DellSystem: GetSWBundle: Unknown TargetOS specified: $TargetOS"
			}
		}
		
		[System.XML.XMLElement]$swbun = $xmldoc.CreateElement("SoftwareBundle")
		$swbun.SetAttribute('schemaVersion','2.0')
		$ID = "$($this.Agile)_$($TargetOS).670"
		$vver = "$($this.Agile).670"
		$path = "PE$($this.Name)-$pathOS-$($this.Agile).XML"
		$swbun.SetAttribute('releaseID', $ID)
		$swbun.SetAttribute('bundleID', $ID)
		$swbun.SetAttribute('dateTime', $this.DateStamp)
		$swbun.SetAttribute('vendorVersion', $vver)
		$swbun.SetAttribute('path', $path)
		$swbun.SetAttribute('bundleType', $btype)
		$swbun.SetAttribute('size', "0")  # figure this out later
		$swbun.AppendChild($this.MakeLangDisplayElement($xmldoc, 'Name', "System Bundle ($displayOS) PE$($this.Name) 670"))
		$elem = $this.MakeLangDisplayElement($xmldoc, 'ComponentType', 'Dell System Bundle')
		$elem.SetAttribute('value','SBDL')
		$swbun.AppendChild($elem)
		$swbun.AppendChild($this.MakeLangDisplayElement($xmldoc, 'Description', "System Bundle ($displayOS) PE$($this.Name) 670"))
		$elem = $this.MakeLangDisplayElement($xmldoc, 'Category', 'OpenManage Systems Management')
		$elem.SetAttribute('value','SM')
		$swbun.AppendChild($elem)
		
		$newnode = $xmldoc.ImportNode($this.TargetSystems, $true)
		$swbun.AppendChild($newnode)
		
		# get the selected TargetOS from the source XML
		$tgtos = $xmldoc.CreateElement("TargetOSes")
		
		$oslist = $this.TargetOSes.GetElementsByTagName("OperatingSystem")
		write-verbose "DellSystem: GetSWBundle: Preparing to search OperatingSystem nodes for match to osCode $TargetOS"
		foreach ($os in $oslist) {
			if ($os.osCode -ieq $TargetOS) {
				write-verbose "DellSystem: GetSWBundle: Found OperatingSystem match"
				$newnode = $xmldoc.ImportNode($os, $true)
				$tgtos.AppendChild($newnode)
			}
		}
		
		$swbun.AppendChild($tgtos)
		
		$swbun.AppendChild($this.MakeLangDisplayElement($xmldoc, 'RevisionHistory', "-"))
		$elem = $this.MakeLangDisplayElement($xmldoc, 'ImportantInfo', "-")
		$elem.SetAttribute('URL','http://support.dell.com')
		$swbun.AppendChild($elem)
		
		# add packages
		$content = $xmldoc.CreateElement("Contents")
		$swbun.AppendChild($content)
		
		$pkglist = $this.GetPackagelist($TargetOS)
		if (-not $pkglist) {
			write-warning "DellSystem: GetSWBundle: No packages found for TargetOS $TargetOS.  This SoftwareBundle for $($this.Name) will have no effect."
		}
		else {
			foreach ($pkg in $pkglist) {
				$elem = $xmlDoc.CreateElement("Package")
				$elem.SetAttribute('path',$pkg.Path)
				$content.AppendChild($elem)
			}
		}
		return $swbun
	}
	
	[Hashtable[]]GetPackageList([string]$TargetOS) {
	
		write-verbose "DellSystem: GetPackageList: Getting list of packages for $($this.Name) for targetOS $TargetOS"
		switch ($TargetOS) {
			'LIN' {
				$pkgrex = '.*\.BIN'
			}
			'WIN64' {
				$pkgrex = '.*_WN64_.*\.EXE'
			}
			'WIN' {
				$pkgrex = '.*_WN32_.*\.EXE'
			}
			default {
				throw "DellSystem: GetPackageList: Unknown TargetOS specified: $TargetOS"
			}
		}
		
		$ospackages = $this.Packages | ? {$_.path -match $pkgrex}
		return $osPackages
	}

}  # DellSystem

Class DellSystemCatalogs {
	[string]$XMLFileName
	[System.XML.XMLDocument]$XMLDoc
	[DellSystem[]]$Systems
	[System.XML.XMLElement[]]$InvNodes
	[string]$DateStamp
	[string]$Version
	[System.XML.XMLElement[]]$SysNodes
	[hashtable[]]$Components
	[string]$DRMStorePath
	[string]$prgactivity
	[string]$prgcurop
	[int]$prgcomplete
	[string]$TempFolder
	
	# reads a system data file that provides the platform details to build into the catalog.
	DellSystemCatalogs([string]$XMLFileName) {
		$this.TempFolder = $env:TEMP
	
		$this.XMLFileName = $XMLFileName
		$this.XMLDoc = [System.XML.XMLDocument]::new()
		$this.XMLDoc.Load($this.XMLFileName)  # load the system data file
		$this.prgactivity = "Generating Base Catalogs"
		$this.prgcurop = "Initializing from XML"
		$this.prgcomplete = 0
		
		if (-not $this.XMLDoc.BaseCatalogs) {
			throw "DellSystemCatalogs: Unable to load BaseCatalogs from $($this.XMLFileName)"
		}
		
		write-verbose "DellSystemCatalogs: Getting BaseCatalogs from $($this.XMLFileName)"
		$this.UpdateProgress()
		
		$this.InvNodes = $this.XMLDoc.BaseCatalogs.GetElementsByTagName("InventoryComponent")
		if ($this.InvNodes.Count -eq 0) {
			throw "DellSystemCatalogs: No InventoryComponent nodes were found in $XMLFileName."
		}	
		
		$this.SysNodes = $this.XMLDoc.BaseCatalogs.GetElementsByTagName("System")
		
		if ($this.SysNodes.Count -eq 0) {
			throw "DellSystemCatalogs: No System nodes were found in $XMLFileName."
		}
		
		$this.Systems = @()
		$prgstep = (10.0 / $this.SysNodes.Count)  # total progress will be 10 % for this phase
		foreach ($sysnode in $this.SysNodes) {
			write-verbose "DellSystemCatalogs: Found System named $($sysNode.Name)"
			$this.Systems += [DellSystem]::new($sysnode)
			$this.prgcomplete += $prgstep
			$this.UpdateProgress()
			
		}
		
		$this.DateStamp = (Get-Date -format 'yyyy-MM-ddTHH:mm:ss') + (Get-timezone).BaseUtcOffset.ToString().Substring(0,6)
		$this.Version = get-date -format 'yy.MM.dd'
		$this.Components = @()
		$this.DRMStorePath = join-path "$([Environment]::GetFolderPath([System.Environment+SpecialFolder]::CommonApplicationData))" 'Dell\drm\store'
		$this.UpdateProgress()
	}
	
	[void] UpdateProgress() {
		if ($this.prgcomplete -gt 100) {
			$this.prgcomplete = 100
		}
		write-progress -activity $this.prgactivity -CurrentOperation $this.prgcurop -PercentComplete $this.prgcomplete
	}
	
	
	[System.XML.XMLElement] MakeLangDisplayElement([System.XML.XMLDocument]$doc, [string]$TagName, [string]$Text) {
		[System.XML.XMLElement]$elem = $doc.CreateElement($TagName)
		$display = $doc.CreateElement('Display')
		$display.SetAttribute('lang','en')
		$display.InnerText = $Text
		$elem.AppendChild($display)
		
		return $elem
	}
	
	[System.XML.XMLElement] MakeInvColElement([System.XML.XMLDocument]$doc, [string]$osCode) {
	#[System.XML.XMLElement] MakeInvColElement([System.XML.XMLDocument]$doc, [string[]]$attributes) {
		##OLD 
		##[System.XML.XMLElement]$elem = $doc.CreateElement('InventoryComponent')
		##foreach ($attrib in $attributes) {
		#	$name,$value = $attrib.Split('=').trim('"')
		#	$elem.SetAttribute($name, $value)
		#}
		
		write-verbose "DellSystemCatalogs: MakeInvColElement: Looking for InventoryCollector Element for OSCode $oscode"
		[System.XML.XMLElement]$invcol = $this.InvNodes | ? {$_.osCode -eq $osCode} | select -first 1 # there should be only one anyway
		
		if ($invcol -eq $null) {
			throw "DellSystemCatalog: MakeInvColElement: An InventoryComponent was not found for osCode $osCode."
		}
		
		write-verbose "DellSystemCatalogs: MakeInvColElement: Importing InventoryCollector XML for $($invcol.path)"
		[System.XML.XMLElement]$elem = $doc.ImportNode($invcol, $true)   #this copies the node from the original doc to the output doc.
		return $elem
		
	}
	
	[void] AddComponents([Hashtable[]]$MoreComponents, [string]$supportedsystem) {
		if (-not $this.Components) {
			$this.Components = @()
		}
		
		foreach ($comp in $MoreComponents) {
			# check for duplicates by path (filename)
			if (-not ($this.Components | ? {$_.Path -eq $comp.Path})) {
				write-verbose "DellSystemCatalogs: AddComponents: Adding $($comp.Path) with support for $supportedsystem"
				$comp.SupportedSystems = @($supportedsystem)
				$this.Components += $comp
			}
			else {
				write-verbose "DellSystemCatalogs: AddComponents: Adding supported system $supportedsystem to $($comp.Path)"
				$existcomp = $this.Components | ? {$_.Path -eq $comp.Path} | select -first 1
				$existcomp.SupportedSystems += $supportedsystem
				
				write-debug "DellSystemCatalogs: AddComponents: $($comp.path) SupportedSystems = $($comp.SupportedSystems)"
			}
		}
	}
	
	# search the software bundles for the given component 
	[void] GetSupportedSystemsXML([Hashtable]$comp, [System.XML.XMLElement]$swcomp, [System.XML.XMLDocument]$xmldoc) {
		if (-not ($comp.SupportedSystems)) {
			write-warning "DellSystemCatalogs: GetSupportedSystems: no supported systems found for $($comp.path)"
			return
		}
		write-verbose "DellSystemCatalogs: GetSupportedSystems: Component $($comp.path) supports the following systems: $($comp.SupportedSystems)"
		$sptsys = $this.Systems | ? {$_.Name -in $comp.SupportedSystems}  # get the objects for the systems
		
		if (-not $swcomp.SelectSingleNode("//SupportedSystems")) { # add if none exists
            $sptsysnode = $xmldoc.CreateElement('SupportedSystems')
            $sptsysnode.SetAttribute('display','1')
            $swcomp.AppendChild($sptsysnode)
        }
        else {
            $sptsysnode = $swcomp.SelectSingleNode("//SupportedSystems")
        }
		
		foreach ($sys in $sptsys) {
			write-debug "DellSystemCatalogs: GetSupportedSystems: Component $($comp.path) adding Brand/model info from system $($sys.Name)"
			$brands = $sys.TargetSystems.GetElementsByTagName('Brand')
			$nodebrands = $sptsysnode.GetElementsByTagName('Brand')
			foreach ($brand in $brands) {
				$found = $false
				# search to make sure we don't add duplicates
				$models = $brand.GetElementsByTagName('Model')
				foreach ($nodebrand in $nodebrands) {
					if ($nodebrand.key -eq $brand.key) {
						$found = $true
						write-debug "Found brandkey $($nodebrand.key)"
						# add the models under the existing brand
						
						$nodemodels = $nodebrand.GetElementsByTagName('Model')
						foreach ($model in $models) {
							$foundm = $false
							foreach ($nodemodel in $nodemodels) {
								if ($model.systemID -eq $nodemodel.systemID) {
									$foundm = $true
									write-debug "Found model $($model.systemID) under brandkey $($nodebrand.key)"
									break # no need to do anything else if found
								}
							}
							if (-not $foundm) {
								# add each model under the brand
								write-debug "Importing model $($model.systemID) info into brand $($nodebrand.key)"
								$newnode = $xmldoc.ImportNode($model, $true)
								$nodebrand.AppendChild($newnode)
							}

						}
						break  # no need to search if found
					}
				}
				if (-not $found) {
					# add the brand node and all model subnodes from TargetSystems
					write-debug "Importing brand $($brand.key) into SupportedSystems"
					$newnode = $xmldoc.ImportNode($brand, $true)
					$sptsysnode.AppendChild($newnode)
				}
			}
		}
		
		#return $sptsysnode
	}
	
	# route the request to the Linux or Windows function depending on the file extension
	[System.XML.XMLElement] GetSWCompXML([hashtable]$comp, [System.XML.XMLDocument]$xmldoc, [string]$DUPSearchPath) {
		$filex = $comp.path.split('.')[-1]
		if ($filex -ieq 'BIN') {
			return $this.GetSWCompXMLLinux($comp, $xmldoc, $DUPSearchPath)
		}
		elseif ($filex -ieq 'EXE') {
			return $this.GetSWCompXMLWindows($comp, $xmldoc, $DUPSearchPath)
		}
		else {
			throw "DellSystemCatalogs: GetSWCompXML: Unknown Target OS for component $($comp.path).  Only Linux and Windows are supported."
		}
		
	}
	
	# extract xml from DUP and return as SoftwareComponent Element
	[System.XML.XMLElement] GetSWCompXMLLinux([hashtable]$comp, [System.XML.XMLDocument]$xmldoc, [string]$DUPSearchPath) {
		write-verbose "DellSystemCatalogs: GetSWCompXMLLinux: Generating SoftwareComponent XML for path $($comp.path)"
		
		if (-not (test-path $DUPSearchPath)) {
			throw "DellSystemCatalogs: GetSWCompXMLLinux: Package Search Path $DUPSearchPath does not exist."
		}
		$pf = get-childitem -path $DUPSearchPath -filter $comp.path -recurse | select -first 1
		
		if (-not $pf) {
			throw "DellSystemCatalogs: GetSWCompXMLLinux: Package file $($comp.path) not found under search path $DUPSearchPath."
		}
		else {
			# this is the path to extract the file to
			$pkgxmlpath = join-path $this.TempFolder ($pf.basename + '.xml')
		}
		
        # make a new clean softwarecomponent node in the target base catalog xml
		[System.XML.XMLElement]$swcomp = $xmldoc.CreateElement('SoftwareComponent')

		#get the bounds of the XML content
		$maniftxmlmarker = grep -m1 -an "^#####Startofpackage#####" $($pf.fullname) | cut -d ":" -f 1
		$duparchivemarker = grep -m1 -an "^#####Startofarchive#####" $($pf.fullname) | cut -d ":" -f 1
		$pkgxmlend = [Convert]::ToInt32($duparchivemarker) - 2
		$pkgxmlstart = [Convert]::ToInt32($maniftxmlmarker) + 1
		
		write-debug "XML data in $($pf.fullname) starts at line $pkgxmlstart and ends at $pkgxmlend"
		
		# cut the file into the xml part only
		write-verbose "DellSystemCatalogs: GetSWCompXMLLinux: Extracting XML to target file $pkgxmlpath"
		$cmdstr = "sh -c 'head -n $pkgxmlend $($pf.fullname.replace('\','/')) | tail -n +$pkgxmlstart > $($pkgxmlpath.replace('\','/'))'"
		write-debug "Command line: $cmdstr"
		invoke-expression "& $cmdstr"
		
		[System.XML.XMLDocument]$pkgxml = [System.XML.XMLDocument]::new()
		$pkgxml.Load($pkgxmlpath)
		
		$swcomproot = $pkgxml.SelectSingleNode("//SoftwareComponent")

		$swcomp.SetAttribute('schemaVersion', '2.4')
		$swcomp.SetAttribute('packageID', $swcomproot.packageID.tostring().substring(0,5))
		$swcomp.SetAttribute('releaseID', $swcomproot.releaseID.tostring().substring(0,5))
		$swcomp.SetAttribute('hashMD5', (get-filehash -path $pf.FullName -algorithm 'MD5').Hash.tolower())
        if (-not $comp.version) {
            $componentversion="1"
        }
        else {
            $componentversion=$comp.version
        }

		$swcomp.SetAttribute('path', "$($comp.folder)\$componentversion\$($comp.path)")
		$swcomp.SetAttribute('dateTime', $swcomproot.dateTime)
		$swcomp.SetAttribute('releaseDate', $swcomproot.releaseDate)
		$swcomp.SetAttribute('vendorVersion', $swcomproot.vendorVersion)
		$swcomp.SetAttribute('dellVersion', $swcomproot.dellVersion)
		$swcomp.SetAttribute('packageType', $swcomproot.packageType)
		$swcomp.SetAttribute('rebootRequired', $swcomproot.rebootRequired)
		$swcomp.SetAttribute('size', $pf.length)
		#containerPowerCycleRequired="0"
		$swcomp.SetAttribute('containerPowerCycleRequired', '0')
		#xmlGenVersion=""
		$swcomp.SetAttribute('xmlGenVersion', '')
		
		foreach ($nodename in @('Name','ComponentType','Description','LUCategory','Category','SupportedDevices','SupportedSystems','RevisionHistory','ImportantInfo','Criticality')) {
			$node = $swcomproot.SelectSingleNode("//$nodename")
			
			if ($node) { 
				$elem = $xmldoc.ImportNode($node, $true)
				$swcomp.AppendChild($elem)
			}
			else {
				write-verbose "DellSystemCatalogs: GetSWCompXMLLinux: Node named $nodename not found in component $($comp.path) package XML."
			}
		}
		
		# fix stuff
		$devices = $swcomp.SelectSingleNode("//SupportedDevices")
		if ($devices) {
			$rollback = $devices.SelectSingleNode("//RollbackInformation")
			while ($rollback) {
				$rollback.parentNode.RemoveChild($rollback)
				$rollback = $devices.SelectSingleNode("//RollbackInformation")
			}
			$payload = $devices.SelectSingleNode("//PayloadConfiguration")
			while ($payload) {
				$payload.ParentNode.RemoveChild($payload)
				$payload = $devices.SelectSingleNode("//PayloadConfiguration")
			}
		}

		write-verbose "DellSystemCatalogs: GetSWCompXMLLinux: Constructing SupportedSystems node for $($comp.Path)"
        # this will add the target systems' branding to the component's branding without causing duplicates.
		$this.GetSupportedSystemsXML($comp, $swcomp, $xmldoc)
		        
		if (-not $swcomp.SelectSingleNode("//RevisionHistory")) {
			write-verbose "DellSystemCatalogs: GetSWCompXMLLinux: Constructing RevisionHistory node for $($comp.Path)"
			$elem = $this.MakeLangDisplayElement($xmldoc, 'RevisionHistory', '-')
						
			$swcomp.AppendChild($elem)
		}
		remove-item $pkgxmlpath  # cleanup
		return $swcomp
	}

	[System.XML.XMLElement] GetSWCompXMLWindows([hashtable]$comp, [System.XML.XMLDocument]$xmldoc, [string]$DUPSearchPath) {
		write-verbose "DellSystemCatalogs: GetSWCompXMLWindows: Generating SoftwareComponent XML for path $($comp.path)"
		
		if (-not (test-path $DUPSearchPath)) {
			throw "DellSystemCatalogs: GetSWCompXMLWindows: Package Search Path $DUPSearchPath does not exist."
		}
		$pf = get-childitem -path $DUPSearchPath -filter $comp.path -recurse | select -first 1
		
		if (-not $pf) {
			throw "DellSystemCatalogs: GetSWCompXMLWindows: Package file $($comp.path) not found under search path $DUPSearchPath."
		}
		
		# copy to local temp first to avoid running from share permissions denied.
		$pftemp = join-path $this.TempFolder $pf.name
		copy-item $pf.fullname $this.TempFolder
		# this is the extract path for the XML file
		$pkgxmlpath = join-path $this.TempFolder ($pf.basename + '.xml')
		$pkgtemp = join-path $this.TempFolder ($pf.basename + '_temp')
		$pkgdotxml = join-path $pkgtemp 'package.xml'
		
		[System.XML.XMLElement]$swcomp = $xmldoc.CreateElement('SoftwareComponent')
	
		write-verbose "DellSystemCatalogs: GetSWCompXMLWindows: Extracting package files to target $pkgtemp"
		
		new-item -itemtype Directory -Path $pkgtemp | out-null
		$cmdstr = "$pftemp /s /extract=""$pkgtemp"""
		write-debug "Command line: $cmdstr"
		invoke-expression "& $cmdstr"
		
		$tries = 5
		while (($tries -gt 0) -and (-not (test-path $pkgdotxml))) {
			write-debug "Waiting for $pkgdotxml"
			start-sleep -seconds 5
			$tries--
		}
		if (-not (test-path $pkgdotxml)) {
			throw "DellSystemCatalogs: GetSWCompXMLWindows: Extract of $($comp.path) failed to produce a package.xml file at $pkgdotxml."
		}
		
		copy-item $pkgdotxml $pkgxmlpath 
		[System.XML.XMLDocument]$pkgxml = [System.XML.XMLDocument]::new()
		$pkgxml.Load($pkgxmlpath)
		
		$swcomproot = $pkgxml.SelectSingleNode("//SoftwareComponent")

		$swcomp.SetAttribute('schemaVersion', '2.4')
		$swcomp.SetAttribute('packageID', $swcomproot.packageID.tostring().substring(0,5))
		$swcomp.SetAttribute('releaseID', $swcomproot.releaseID.tostring().substring(0,5))
		$swcomp.SetAttribute('hashMD5', (get-filehash -path $pf.FullName -algorithm 'MD5').Hash.tolower())
        if (-not $comp.version) {
            $componentversion="1"
        }
        else {
            $componentversion=$comp.version
        }
		$swcomp.SetAttribute('path', "$($comp.folder)\$componentversion\$($comp.path)")
		$swcomp.SetAttribute('dateTime', $swcomproot.dateTime)
		$swcomp.SetAttribute('releaseDate', $swcomproot.releaseDate)
		$swcomp.SetAttribute('vendorVersion', $swcomproot.vendorVersion)
		$swcomp.SetAttribute('dellVersion', $swcomproot.dellVersion)
		$swcomp.SetAttribute('packageType', $swcomproot.packageType)
		$swcomp.SetAttribute('rebootRequired', $swcomproot.rebootRequired)
		$swcomp.SetAttribute('size', $pf.length)
		#containerPowerCycleRequired="0"
		$swcomp.SetAttribute('containerPowerCycleRequired', '0')
		#xmlGenVersion=""
		$swcomp.SetAttribute('xmlGenVersion', '')
		
		
		foreach ($nodename in @('Name','ComponentType','Description','LUCategory','Category','SupportedDevices','RevisionHistory','ImportantInfo','Criticality')) {
			$node = $swcomproot.SelectSingleNode("//$nodename")
			
			if ($node) { 
				$elem = $xmldoc.ImportNode($node, $true)
				$swcomp.AppendChild($elem)
			}
			else {
				write-verbose "DellSystemCatalogs: GetSWCompXMLWindows: Node named $nodename not found in component $($comp.path) package XML."
                
                if ($nodename -eq 'RevisionHistory') {
                    write-verbose "DellSystemCatalogs: GetSWCompXMLWindows: Constructing RevisionHistory node for $($comp.Path)"
                    $elem = $this.MakeLangDisplayElement($xmldoc, 'RevisionHistory', '-')
                                
                    $swcomp.AppendChild($elem)
                }
			}
		}
		
		# remove extra items such as rollbackinformation and payloadconfiguration that aren't required in the base catalog schema
		$devices = $swcomp.SelectSingleNode("//SupportedDevices")
		if ($devices) {
			$rollback = $devices.SelectSingleNode("//RollbackInformation")
			while ($rollback) {
				$rollback.parentNode.RemoveChild($rollback)
				$rollback = $devices.SelectSingleNode("//RollbackInformation")
			}
			$payload = $devices.SelectSingleNode("//PayloadConfiguration")
			while ($payload) {
				$payload.ParentNode.RemoveChild($payload)
				$payload = $devices.SelectSingleNode("//PayloadConfiguration")
			}
		}
        # we will construct the SupportedSystems using only the systems defined in the SystemsData XML
        write-verbose "DellSystemCatalogs: GetSWCompXMLWindows: Constructing SupportedSystems node for $($comp.Path)"
        $this.GetSupportedSystemsXML($comp, $swcomp, $xmldoc)

		remove-item -recurse -force $pkgtemp  # cleanup
		remove-item $pftemp
		remove-item $pkgxmlpath  # cleanup
		
		return $swcomp
	}
	
	[void] CreateBaseCatalogXML([string[]] $SystemNames, [string]$OutputXMLFile, [string]$DUPSearchPath, [string[]]$TargetOSes) {
		write-verbose "CreateBaseCatalogXML: Creating all-inclusive base catalog for $SystemNames to file named $OutputXMLFile"
		$this.prgcurop = "Starting BaseCatalog XML"
		
		$this.UpdateProgress()
		$prgstep = 30.0 / (($SystemNames.Count * $TargetOSes.Count) + 1 )
		
		[System.XML.XMLDocument]$OutputDoc = [System.XML.XMLDocument]::new()
		$dec = $outputdoc.CreateXmlDeclaration("1.0","utf-16le", $null)
		$outputdoc.AppendChild($dec)

		[System.XML.XMLElement]$Manifest = $OutputDoc.CreateElement("Manifest")
		
		# make main headers
		$Manifest.SetAttribute('baseLocation',"ftp.dell.com")
		$Manifest.SetAttribute('dateTime', $this.DateStamp)
		$Manifest.SetAttribute('identifier', (new-guid))
		$Manifest.SetAttribute('releaseID', "ABCDE")
		$Manifest.SetAttribute('version', $this.Version)
		$Manifest.SetAttribute('predecessorID', (new-guid))

		$relnotes = $this.MakeLangDisplayElement($outputdoc, "ReleaseNotes", 'Release Notes')
		$Manifest.AppendChild($relnotes)
		
		#$attribsetlin = @('schemaVersion="2.0"','releaseID="VPJT7"','hashMD5="708e3774b98db772566007a092bbd218"','path="FOLDER05077911M/1/invcol_VPJT7_LN64_18_06_000_248_A00"','dateTime="2018-07-09T10:50:31Z"','releaseDate="July 09, 2018"','vendorVersion="18.06.000.248"','dellVersion="A00"','osCode="LIN64"')
		$invcolnodelin = $this.MakeInvColElement($outputdoc, 'LIN64')
		$Manifest.AppendChild($invcolnodelin)
		
		#$attribsetwin = @('schemaVersion="2.0"','releaseID="VPJT7"','hashMD5="ef4c8f851d4f0aaf4e1aafe3eba8bada"','path="FOLDER05077914M/1/invcol_VPJT7_WIN64_18_06_000_248_A00.exe"','dateTime="2018-07-09T10:50:31Z"','releaseDate="July 09, 2018"','vendorVersion="18.06.000.248"','dellVersion="A00"','osCode="WIN64"')
		$invcolnodewin = $this.MakeInvColElement($outputdoc, 'WIN64')
		$Manifest.AppendChild($invcolnodewin)
		$this.prgcomplete += $prgstep
		$this.UpdateProgress()
		
		#  Make SoftwareBundle per system/OS
		foreach ($name in $SystemNames) {
			
			$sys = $this.Systems | ? {$_.Name -eq $name}
			if (-not $sys) {
				write-error "A DellSystem object with the name $name was not found in the collection."
			}
			foreach ($tgtOS in $TargetOSes) {			
				$this.prgcurop = "Building SoftwareBundle for $name $tgtOS"
				$this.UpdateProgress()
				[System.XML.XMLElement]$bundle = $sys.GetSWBundle($OutputDoc, $tgtOS)
				$Manifest.AppendChild($bundle)
				$this.AddComponents($sys.GetPackageList($tgtOS), $sys.Name)
				$this.prgcomplete += $prgstep
			}
		}
		
		# make a SoftwareComponent per package
		write-verbose "DellSystemCatalogs:  Generating SoftwareComponent list"
		$prgstep = 40.0 / ($this.Components.Count )
		foreach ($comp in $this.Components) {
			$this.prgcurop = "Generating SoftwareComponent node for $($comp.path)"
			$this.UpdateProgress()
			$elem = $this.GetSWCompXML($comp, $outputdoc, $DUPSearchPath)
			$Manifest.AppendChild($elem)
			$this.prgcomplete += $prgstep
		}
		
		$elem = $outputdoc.CreateElement("Prerequisites")
		$Manifest.AppendChild($elem)
		
		$outputdoc.AppendChild($Manifest)
		
		
		$OutputDoc.Save($OutputXMLFile)
	}
	
	# assumes that CreateBaseCatalogXML was already completed so that Components list is populated
	# will copy the bin and bin.sign files to the appropriate folder in DRM store
	# so that DRM can generate the export packages by whatever means selected.
	[void] SetupDellRepoMgrStore([string]$DUPSearchPath) {
		write-verbose "DellSystemCatalogs: SetupDellRepoMgrStore: Copying SoftwareComponent bin files to Dell Repo Mgr Store."
		$this.prgcurop = "Updating Dell Repository Manager store"
		
		$this.UpdateProgress()
		$prgstep = 20.0 / ($this.Components.Count )
		
		if (-not (test-path $this.DRMStorePath)) {
			throw "DellSystemCatalogs: SetupDellRepoMgrStore:  Dell Repo Mgr Store path not found at $($this.DRMStorePath)."
		}
		
		write-verbose "DellSystemCatalogs: SetupDellRepoMgrStore:  Searching for binary files in $DUPSearchPath"
		foreach ($node in $this.InvNodes) {
			$parts = $node.path.split('/')
			$pfbin = get-childitem -path $DUPSearchPath -filter $parts[-1] -recurse | select -first 1
			$pfsign = ''
			$targetsign = ''
			
			if (-not $pfbin) {
				write-warning "DellSystemCatalogs: SetupDellRepoMgrStore:  Inventory Collector file $($node.path) not found in $DUPSearchPath."
			}
			if (-not ($pfbin.FullName -ilike '*.EXE')) {  # linux invcol file has no .bin extension
				$pfsign = get-item "$($pfbin.fullname).sign"
				if (-not $pfsign) {
					write-warning "DellSystemCatalogs: SetupDellRepoMgrStore:  Component signature file for $($parts[-1]) not found in $DUPSearchPath."
				}			
			}
			$pkgpath = join-path $parts[0] $parts[1]
			$targetpath = join-path $this.DRMStorePath $pkgpath
			$targetbin = join-path $targetpath $parts[-1]
			if ($pfsign) {
				$targetsign = join-path $targetpath $pfsign.Name
			}
			
			if (-not (test-path $targetpath)) {
				new-item -ItemType Directory -path $targetpath
			}
			$this.prgcurop = "Copying $($pfbin.fullname) to the DRM store"
			$this.UpdateProgress()
			
			if (-not (test-path $targetbin)) {
				write-verbose "DellSystemCatalogs: SetupDellRepoMgrStore: Copying $($pfbin.fullname) to $targetpath."
				
				copy-item -Force -Path $pfbin.FullName -Destination $targetpath
				if ($pfsign -and (-not (test-path $targetsign))) {
					write-verbose "DellSystemCatalogs: SetupDellRepoMgrStore: Copying $($pfsign.fullname) to $targetpath."
					copy-item -Force -Path $pfsign.Fullname -Destination $targetpath
					
				}
			}
			else {
				write-verbose "DellSystemCatalogs: SetupDellRepoMgrStore: Component $($pfbin.Name) already in $targetpath."
			}
			$this.prgcomplete += $prgstep		
		}
		
		foreach ($comp in $this.Components) {
			$pfbin = get-childitem -path $DUPSearchPath -filter $comp.path -recurse | select -first 1
			$pfsign = ''
			$targetsign = ''
			
			if (-not $pfbin) {
				write-warning "DellSystemCatalogs: SetupDellRepoMgrStore:  Component file $($comp.path) not found in $DUPSearchPath."
			}
			if ($pfbin.FullName -ilike '*.BIN') {
				$pfsign = get-item "$($pfbin.fullname).sign"
				if (-not $pfsign) {
					write-warning "DellSystemCatalogs: SetupDellRepoMgrStore:  Component signature file for $($comp.path) not found in $DUPSearchPath."
				}			
			}
			$pkgpath = "$($comp.folder)\1\"
			$targetpath = join-path $this.DRMStorePath $pkgpath
			$targetbin = join-path $targetpath $pfbin.name
			if ($pfsign) {
				$targetsign = join-path $targetpath $pfsign.Name
			}
			
			if (-not (test-path $targetpath)) {
				new-item -ItemType Directory -path $targetpath
			}
			$this.prgcurop = "Copying $($pfbin.fullname) to the DRM store"
			$this.UpdateProgress()
				
			if (-not (test-path $targetbin)) {
				write-verbose "DellSystemCatalogs: SetupDellRepoMgrStore: Copying $($pfbin.fullname) to $targetpath."
				
				copy-item -Force -Path $pfbin.FullName -Destination $targetpath
				if ($pfsign -and (-not (test-path $targetsign))) {
					write-verbose "DellSystemCatalogs: SetupDellRepoMgrStore: Copying $($pfsign.fullname) to $targetpath."
					copy-item -Force -Path $pfsign.Fullname -Destination $targetpath
					
				}
			}
			else {
				write-verbose "DellSystemCatalogs: SetupDellRepoMgrStore: Component $($pfbin.Name) already in $targetpath."
			}
			$this.prgcomplete += $prgstep
		}
	}
}
