Param(
    [Parameter(HelpMessage = "The GitHub repository name running the action", Mandatory = $true)]
    [string] $gitRepoName
)

# allow powershell script to be run remotely from github actions
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process

# set working directories
$buildroot = 'C:\Linc-GithubWorkflows\AppBuilds\'
$workPath = 'C:\actions-runner\_work\' + $gitRepoName + '\' + $gitRepoName

# get app.json file of project
$appjsonfilepath = $workpath + '\app.json'

# read app.json file into variables for later use
$appjsonfile = Get-Content $appjsonfilepath | ConvertFrom-Json
$app_dependencies = $appjsonfile.dependencies
$appName = $appjsonfile.name.Replace(" ","-").Replace("-","")
$appSourcePath = $buildroot + $appName

# check dependencies for Linc Extension Access
foreach ($d in $app_dependencies)
    {
        if ($d.name.Replace(" ","-").Replace("-","") -eq 'LincExtensionAccess')
        {
            $librarySourcePath = $buildroot + $d.name.Replace(" ","-").Replace("-","")
            $hasLibraryFile = $true
        }
    }

# set product name to search for on marketplace offers
$productName = $productname = $appjsonfile.name.Replace("-"," ").Replace("Linc ","")

# set valid names for app and library files
$appFilePath = $appSourcePath + '\*.app'
$appFile = (Get-Item $appFilePath).FullName
if ($hasLibraryFile)
    {
        $libAppFilePath = $librarySourcePath + '\*.app'
        $libAppFile = (Get-Item $libAppFilePath).FullName
    }

# publish to appsource
Import-Module BcContainerHelper
Import-Module Az.Storage

$tenantId = "9d9672cd-de63-40b4-923d-3651563114a2"
$clientId = "7bb201ba-ae54-4c5e-b470-28826e397a9b"
$clientSecret = "jN38Q~005vNI8BYDNjgvqRshg3KHaOiy2f8oAcgv"

$authcontext = New-BcAuthContext `
    -clientID $clientId `
    -clientSecret $clientSecret `
    -Scopes "https://api.partner.microsoft.com/.default" `
    -TenantID $tenantId

$products = Get-AppSourceProduct -authContext $authcontext -silent
$productId = ($products | Where-Object { $_.name -eq $productName }).id
if (!$productId)
    {Write-Host -ForegroundColor Red 'Unable to find existing AppSource product'}
else
    {
        if ($hasLibraryFile)
            {New-AppSourceSubmission -authContext $authContext -productId $productId -appFile $appFile -libraryAppFiles $libAppFile -autoPromote -doNotWait}
        else
            {New-AppSourceSubmission -authContext $authContext -productId $productId -appFile $appFile -autoPromote -doNotWait}
    }