<#
    .SYNOPSIS
	MakeSDSBundle.ps1 executes command-line steps using the Dell EMC Repository Manager (DRM) to create 
	a Smart Deployment Script firmware update bundle from a given system base catalog.

	.DESCRIPTION
	The script imports a given Base Catalog XML file in the the local instance of DRM
	and creates a repository for a selected set of systems (or all systems in the catalog if no system 
	selection option is provided.) 
	The the script exports the desired firmware update packages into a Smart Deployment Script bundle 
	so that they can be delivered to target systems.   The SDS bundle can be generated for linux or windows
	systems, so a paramter must indicate which is desired.
	
	.PARAMETER BaseCatalog
	The full path to the desired BaseCatalog XML file to use when creating the repository.
	
	.PARAMETER RepositoryName
	A Name for the Repository that will be created in DRM.  This can be accessed later in the GUI if desired.
	
	.PARAMETER SystemNames
	A list of strings that pecifies the names of Systems to be included in the repository from tyhe BaseCatalog.
	This parameter is options, excluding it will include ALL systems in the catalog.
	
	.PARAMETER TargetOSes
	A list of enumerated strings <LIN, WIN, WIN64> that specifies the operating systems the script will generate 
	SDS bundles for.  This parameter is optional.  Leaving it blank will generate for all operating systems
	that are supported by the BaseCatalog
	
	.PARAMETER OutputPath
	The full path to a writable file location where the SDS script folder will be created.
	
	.EXAMPLE
	.\MakeSDSBundle.ps1 -BaseCatalog c:\work\ATT_Updates\Build\ATTBaseCatalog.xml -SystemNames 'DSS9600','DCS1610'
		-OutputPath c:\work\ATT_Updates\Build\output -TargetOSes 'LIN'
		
	.EXAMPLE
	.\MakeSDSBundle.ps1 -BaseCatalog c:\work\ATT_Updates\Build\ATTBaseCatalog.xml
		-OutputPath c:\work\ATT_Updates\Build\output	
	
	.NOTES
	Dell EMC Repository Manager 3.0+ must be installed on the local system for this script to function.
#>

[cmdletbinding()] 
param(
	[parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$BaseCatalog,
	[parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$RepositoryName,
	[parameter(Mandatory=$false)][string[]]$SystemNames, 
	[parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$OutputPath,
	[parameter(Mandatory=$false)][ValidateSet('LIN','WIN','WIN64')][string[]]$TargetOSes
)

# make sure DRM is installed
$DRMPath = join-path "$([Environment]::GetFolderPath([System.Environment+SpecialFolder]::ProgramFiles))" 'Dell\Dell EMC Repository Manager'

if (-not (test-path $DRMPath)) {
	throw "The DRM ProgramFiles Folder does not exist in the expected location $DRMPath.  The Dell EMC Repository Manager may not be installed."
}

# make sure BaseCatalog exists
if (-not (test-path $BaseCatalog)) {
	throw "The file $BaseCatalog was not found."
}

# make sure outputpath exists
if (-not (test-path $OutputPath)) {
	throw "The folder $OutputPath was not found."
}

$SDSScriptTypes = @()
if ($TargetOSes -and ($TargetOSes.Count -gt 0)) {
	foreach ($tgtos in $TargetOSes) {
		if (($tgtos -eq 'LIN') -and (-not ('linux' -in $SDSScriptTypes))) {
			write-verbose "TargetOS Linux detected."
			$SDSScriptTypes += @('linux')
		}
		if (($tgtos -in 'WIN','WIN64') -and (-not ('windows' -in $SDSScriptTypes))) {
			write-verbose "TargetOS Windows detected."
			$SDSScriptTypes += @('windows')
		}
	}
}
if (-not $SDSScriptTypes) {
	write-verbose "No TargetOSes were selected, defaulting to both linux and windows."
	$SDSScriptTypes = @('linux','windows')
}

# create the repository
$platlist = ""
if ($SystemNames -and ($SystemNames.Count -gt 0)) {
	$commalist = "$SystemNames" -replace ' ',','   # print out the systemnames as a comma-separated list
	$platlist = "--inputplatformlist=$commalist"
}

# create the repo with only selected systems (platforms) but include all available OS for now
$commandline = "'$DRMPath\drm.bat' --create --repository=$RepositoryName --source=$BaseCatalog $platlist "
$result = invoke-expression "& $commandline"

if ($result -eq "Application instance already running") {
	throw "The DRM is already running.  Close the GUI and run the command again."
}

if (-not ($result -match 'Creating repository')) {
	throw "There was an error creating the repository.\n$result"
}
write-verbose "Waiting 10 secs for Repository create to complete..."
sleep -seconds 10

# get the repo info to verify it is there
$commandline = "'$DRMPath\drm.bat' --repository=$RepositoryName --details"
$result = invoke-expression "& $commandline"

if ($result -match 'Exception occurred:') {
	throw "The repository $RepositoryName was not found after the create step." 
}

if (-not ($result -match 'Listing version information')) {
	throw "Unexpected result after creating repository $RepositoryName"
}
$lines = $result -split '\n'
$fields = $lines[-2] -split '  ' | ? {$_ -ne ''} | % {$_.trim()}
$RepositoryVersion = $fields[0]
$RepositorySize = $fields[1]

write-verbose "Created Repository named $RepositoryName   Version: $RepositoryVersion  Size: $RepositorySize."

# export the SDS bundle
foreach ($os in $SDSScriptTypes) {
	write-verbose "Exporting SDSScript Bundle for $repositoryname os = $os"
	$commandline = "'$DRMPath\drm.bat' --non-interactive --repository='$($RepositoryName):$($RepositoryVersion)' --deployment-type=smartscript --script-type=$os --location='$OutputPath'"
	$result = invoke-expression "& $commandline"
	
	if (-not ($result -match 'Job submitted')) {
		write-warning "Failed to export SDSSCript for $RepositoryName for os $os.\n$result"
	}
	else { # check for completion
		do {
			write-verbose "Checking for completion of job."
			sleep -seconds 15
			$commandline = "'$DRMPath\drm.bat' --list=job"
			$result = invoke-expression "& $commandline"
			$line = $result -split '\n' | select -last 2 | select -first 1 # 2nd to last line is latest job. last line is blank
			$fields = $line -split '  ' | ? {$_ -ne ''} | % {$_.trim()}
		} while ($fields[1] -eq 'RUNNING')
	
		if ($fields[1] -ne 'SUCCESS') {
			write-warning "The job $($fields[0]) completed with status $($fields[1])"
		}
		else {
			$filepath = join-path $OutputPath (($fields[0] -replace '/','_' ) -replace ':','')
			if (test-path $filepath) {
				$newfilename = "$($RepositoryName)_$($os)_SDS"
				rename-item -path $filepath -newname $newfilename
				$newfilepath = join-path $outputpath $newfilename
				write-host "Export job completed successfully! Files located in $newfilepath"
			}
			else {
				write-warning "Export should have placed files at $filepath but they were not found!"
			}
			
		}
	}
}
