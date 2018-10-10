# CatalogConvert.ps1
# fix schema problems in DRM base catalogs generated from Agile

[CmdletBinding()]  Param(  
	[ValidateNotNullOrEmpty()]  
	[ValidateScript({(Test-Path $_) -and ((Get-Item $_).Extension -eq ".xml")})]  
	[Parameter(ValueFromPipeline=$True,Mandatory=$True)]  
	[string]$FilePath,
	[ValidateNotNullOrEmpty()]  
	[ValidateScript({$_.EndsWith(".xml")})]  
	[Parameter(ValueFromPipeline=$True,Mandatory=$True)]  
	[string]$OutputFilePath
)  
  
Begin  
	{Write-Verbose "$($MyInvocation.MyCommand.Name):: Function started"}  
	  
Process  
{  
    if ($PSBoundParameters['Debug']) { $DebugPreference = 'Continue'}
	Function GetDUPSize {
		param([string] $URL)
		$dupsize = 0
		write-verbose "GetDUPSize: Checking for HTTP response at $URL"
		$response = curl -method Head -Uri $URL
		
		if ($response.StatusCode -eq 200) {
			$dupsize = $response.Headers['Content-Length']
		}
		else {
			write-warning "GetDUPSize():  Failed to get the DUP at $URL.   Returned $($response.StatusCode)."
			
		}
		return $dupsize
	}

	Function GetCategoryName {
		param([string]$catname)
		
		switch ($catname) {
			'DI' {return 'Diagnostics Application'}
			'NI' {return 'Network'}
			'SF' {return 'SAS RAID'}
			'SE' {return 'SAS Non-RAID'}
			'SA' {return 'Serial ATA'}
			'BI' {return 'BIOS'}
			'VI' {return 'Video Driver'}
			'AS' {return 'SAS Drive'}
			'CS' {return 'Chipset Driver'}
		}
		return $catname
	}

	Function GetCriticalityString {
		param([string]$crit)
		
		switch ($crit) {
			'1' {return 'Recommended-Optional'}
			'2' {return 'Urgent-Recommended'}
		}
		return 'Recommended-Optional'
	}
	
	Function RemoveSoftwareComponent {
		param($manifest, $swcompid)
		
		write-debug "SoftwareComponent id = [$swcompid]."
	
		foreach ($sc in $manifest.SoftwareComponent) {
			if ($sc.hashmd5 -ieq $swcompid) {
				$swcomp = $sc
				break # found it so quit
			}
		}
		$filename = $swcomp.path.Split('/')[-1]  # last part of split
		
		write-verbose "Removing $filename from Catalog"
		
		# remove from Contents of SoftwareBundles
		foreach ($sb in $manifest.SoftwareBundle) {
			foreach ($pkg in $sb.Contents) {
				if ($pkg.path -ieq $filename) {
					write-verbose "Removing $filename from SoftwareBundle $($sb.Name.Display.InnerText) Contents"
					$pkg.ParentNode.RemoveChild($pkg) | out-null
				}
			}
		}
		
		# remove from list of components
		write-verbose "Removing $filename from list of SoftwareComponents"
		$swcomp.ParentNode.RemoveChild($swcomp) | out-null

	}
	
	$xmldata = [XML](gc $FilePath)

	if (-not $xmldata.Manifest) {
		write-error "The file $FilePath does not contain a valid DRM base catalog.  The Manifest node is missing or broken."
	}
	elseif (-not $xmldata.Manifest.InventoryComponent) {
		write-error "The file $FilePath does not contain a valid DRM base catalog.  There are no Inventory Collectors included (InventoryComponent)."
	}
	elseif (-not $xmldata.Manifest.SoftwareBundle) {
		write-error "The file $FilePath does not contain a valid DRM base catalog.  There are no Software Bundles defined."
	}
	elseif (-not $xmldata.Manifest.SoftwareComponent) {
		write-error "The file $FilePath does not contain a valid DRM base catalog.  There are no Software Components defined."
	}
	else {
		# change the version to today's date
		$newver = get-date -format "yy.MM.dd"
		$xmldata.Manifest.SetAttribute('version', $newver)
		
		#fix bundles
		foreach ($sb in $xmldata.Manifest.SoftwareBundle) {
			# process the bundles
			if ($sb.schemaVersion -ne '2.0') {
				write-verbose "In softwarebundle $($sb.releaseID) correcting schemaVersion to 2.0"
				$sb.schemaVersion = '2.0'
			}
		}
		# fix components
		foreach ($sc in $xmldata.Manifest.SoftwareComponent) {
			# process the components
			$compname = "$($sc.releaseID).$($sc.packageType)"

			# remove any Drivers, we only want firmware
			if ($sc.ComponentType.value -ieq 'DRVR') {
				write-warning "Removing a Driver component $($sc.Name.Display.InnerText)."
	
				$filename = $sc.path.Split('/')[-1]  # last part of split
				write-verbose "Removing $filename from Catalog"
				
				# remove from Contents of SoftwareBundles
				foreach ($sb in $xmldata.Manifest.SoftwareBundle) {
					foreach ($pkg in $sb.Contents) {
						if ($pkg.path -ieq $filename) {
							write-verbose "Removing $filename from SoftwareBundle $($sb.Name.Display.InnerText) Contents"
							$pkg.ParentNode.RemoveChild($pkg) | out-null
						}
					}
				}
				
				# remove from list of components
				write-verbose "Removing $filename from list of SoftwareComponents"
				$sc.ParentNode.RemoveChild($sc) | out-null

				continue
			}
			# check DUP Size by trying to get the header from web
			try {
				$dupsize = GetDUPSize("http://{0}/{1}" -f $xmldata.Manifest.baseLocation, $sc.path)
			}
			catch {
				write-warning "Removing SoftwareComponent $($sc.Name.Display.InnerText) from catalog since it is not downloadable."
				$filename = $sc.path.Split('/')[-1]  # last part of split
				write-verbose "Removing $filename from Catalog"
				
				# remove from Contents of SoftwareBundles
				foreach ($sb in $xmldata.Manifest.SoftwareBundle) {
					foreach ($pkg in $sb.Contents) {
						if ($pkg.path -ieq $filename) {
							write-verbose "Removing $filename from SoftwareBundle $($sb.Name.Display.InnerText) Contents"
							$pkg.ParentNode.RemoveChild($pkg) | out-null
						}
					}
				}
				
				# remove from list of components
				write-verbose "Removing $filename from list of SoftwareComponents"
				$sc.ParentNode.RemoveChild($sc) | out-null

				continue
			}
			
			$sc.SetAttribute('size',$dupsize) | out-null

			
			if ($sc.schemaVersion -ne '2.4') {
				write-verbose "In softwarecomponent $compname correcting schemaVersion to 2.4"
				$sc.schemaVersion = '2.4'			
			}
			if (-not $sc.RevisionHistory) {
				write-verbose "In softwarecomponent $compname adding missing RevisionHistory."
				$newrh = $xmldata.CreateElement('RevisionHistory')
				$sc.AppendChild($newrh) | out-null
				$disp = $xmldata.CreateElement('Display')
				$disp.SetAttribute('lang','en') | out-null
				$newrh.AppendChild($disp) | out-null
				$cdata = $xmldata.CreateCDataSection('-')
				$disp.AppendChild($cdata) | out-null
			}
			if (-not $sc.ImportantInfo.Display) {
				write-verbose "In softwarecomponent $compname adding missing ImportantInfo."
				$disp = $xmldata.CreateElement('Display')
				$disp.SetAttribute('lang','en') | out-null
				$sc.ImportantInfo.AppendChild($disp) | out-null
				$cdata = $xmldata.CreateCDataSection('NA')
				$disp.AppendChild($cdata) | out-null
			}
			# fix Category and LUCategory
			if ($sc.LUCategory.value -eq 'NONE') {
				write-verbose "In softwarecomponent $compname fixing LUCategory."
				$cname = GetCategoryName($sc.Category.value)
				$sc.LUCategory.value = $cname
				#$cdata = $xmldata.CreateCDataSection($cname)
				#$sc.Category.Display.ReplaceChild($cdata) | out-null
				#$sc.LUCategory.Display.ReplaceChild($cdata) | out-null
			}
			
		}
	
		#output the modified result
		#$fo = (Get-Item $FilePath)
		#$outputfile = $fo.Basename + '.new' + $fo.Extension
		write-verbose "Writing Data out to $outputfilepath"
		$xmldata.Save((join-path $pwd $outputfilepath))		
	}
	
	

}