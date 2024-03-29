<#
	.SYNOPSIS
	MakeSystemCatalog.ps1 processes an input set of XML and a collection of DUP packages
	to produce an output XML file that serves as a Base Catalog for Dell Repository Manager (DRM).

	.DESCRIPTION
	The script processes a set of <System> nodes defined in the input XML file that are each identified by 
	a platform Name such as 'DSS9600' and a BIOS systemID. Each <System> also defines a list of DUP packages
	by binary file name (ex. BIOS_XX64W_LN_1.5.4.BIN) and Agile Folder number (ex. FOLDER05077911M) that 
	comprise the list of update packages that are desired to be delivered for that platform.
	
	The script extracts details from the DUP packages and compiles the XML file necessary to import into 
	Dell Repository Manager (DRM) as a Base Catalog for the purpose of creating update repositories in order to 
	generate deliverable update scripts. It also ensures that the .EXE, .BIN and .BIN.sign files for each DUP 
	package are copied to the correct folders in the DRM Store location on the local system, assuming that DRM 
	is installed on the local system.
	
	Using the Base Catalog generated by this script, systems that are not included in the standard Dell 
	catalogs for DRM can be supported for DRM-style update deliverables, such as creating a file share repository, 
	or a Smart Deployment Script (SDS).
	

	.PARAMETER SystemNames
	An array of strings [string[]] that determines which of the predefined <System> nodes from the SystemDataFile 
	will be included in the OutputCatalog.

	.PARAMETER SystemDataFilePath
	A string that specified the full path and file name of the SystemDataFile, an XML file that defines all of 
	the <System> nodes and their required packages and identifying information. This cannot be null or empty.
	
	.PARAMETER OutputCatalogPath
	A string that specifies the full path and file name of the OutputCatalogPath, a file that will be created by 
	the script and can be used as a Base Catalog in DRM.  This cannot be null or empty.
	
	.PARAMETER DUPSearchPath
	A string that specifies the root folder under which to search for DUP packages by filename.  No specific 
	folder structure is required but it is assumed that all DUPs for all systems will be found under one path 
	hierarchy.  If more than one copy of a DUP is present the first one found will be used.
	
	.PARAMETER TargetOSes
	An array of strings [string[]] that determines which Target Operating Systems will be included in the base catalog.
	Allowed values are 'LIN', 'WIN64', and 'WIN'.  Default is 'LIN' only. More than one OS can be specified at a time.
	
	.EXAMPLE
	.\MakeSystemCatalog.ps1 -SystemNames 'DSS9600','DCS1610' -SystemDataFilePath 'c:\work\ATT_Updates\ATTSystemData.xml' -OutputCatalogPath 'c:\work\ATT_Updates\ATTBaseCatalog.xml' -DUPSearchPath 'c:\work\ATT_Updates\' -TargetOSes 'LIN','WIN64'
	
	.NOTES
		Requires the following installs:
			Powershell 5.0 (included in Microsoft Windows 10)
			GIT for Windows in order to use sh.exe to extract the .BIN file contents. (https://git-scm.com/download/win)
			
		Some Warning messages may appear during execution.  This is normal. The script will attempt to supply any 
		missing information from the DUP packages with schema-appropriate XML.
		
		Add the -Verbose option to the command line to see more details about the operation of the script.
		
		To view Debug messages set the value $DebugPreference = 'Continue' at the command line before executing.
#>
using module ./DellCatalogClasses.psm1

[cmdletbinding()] 
param(
	[parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string[]]$SystemNames, 
	[parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$SystemDataFilePath,
	[parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$OutputCatalogPath,
	[parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$DUPSearchPath,
	[parameter(Mandatory=$false)][ValidateSet('LIN','WIN','WIN64')][string[]]$TargetOSes = 'LIN'
)



if ($PSBoundParameters['Debug']) {
    $DebugPreference = 'Continue'
}

$dsc = [DellSystemCatalogs]::new($SystemDataFilePath)
$dsc.CreateBaseCatalogXML($systemnames, $OutputCatalogPath, $DUPSearchPath, $TargetOSes )
$dsc.SetupDellRepoMgrStore($DUPSearchPath)