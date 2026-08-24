param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'

function Release-ComObject {
    param([object]$Object)

    if ($null -ne $Object) {
        try {
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($Object)
        }
        catch {
        }
    }
}

function Test-BenignOfficeDisconnect {
    param(
        [Parameter(Mandatory = $true)]
        [System.Management.Automation.ErrorRecord]$ErrorRecord,

        [Parameter(Mandatory = $true)]
        [string]$TargetPath
    )

    if (-not (Test-Path -LiteralPath $TargetPath)) {
        return $false
    }

    try {
        $targetItem = Get-Item -LiteralPath $TargetPath
        if ($targetItem.Length -le 0) {
            return $false
        }
    }
    catch {
        return $false
    }

    $message = [string]$ErrorRecord.Exception.Message
    $hresult = 0
    try {
        $hresult = [int64]$ErrorRecord.Exception.HResult
    }
    catch {
        $hresult = 0
    }

    if ($hresult -eq -2147417848) {
        return $true
    }

    if ($message -match 'RPC_E_DISCONNECTED' -or $message -match '0x80010108') {
        return $true
    }

    if ($message -match 'отключен от клиентов' -or $message -match 'disconnected from its clients') {
        return $true
    }

    return $false
}

function Export-WithWord {
    param(
        [string]$SourcePath,
        [string]$TargetPath
    )

    $word = $null
    $doc = $null

    try {
        $word = New-Object -ComObject Word.Application
        $word.Visible = $false
        $word.DisplayAlerts = 0

        $doc = $word.Documents.Open($SourcePath, $false, $true)
        $doc.ExportAsFixedFormat($TargetPath, 17)
        $doc.Close($false)
    }
    finally {
        if ($doc) {
            Release-ComObject -Object $doc
        }

        if ($word) {
            try {
                $word.Quit()
            }
            catch {
            }

            Release-ComObject -Object $word
        }
    }
}

function Export-WithPowerPoint {
    param(
        [string]$SourcePath,
        [string]$TargetPath
    )

    $powerpoint = $null
    $presentation = $null

    try {
        $powerpoint = New-Object -ComObject PowerPoint.Application
        $presentation = $powerpoint.Presentations.Open($SourcePath, $true, $false, $false)
        $presentation.ExportAsFixedFormat($TargetPath, 2)
        $presentation.Close()
    }
    finally {
        if ($presentation) {
            Release-ComObject -Object $presentation
        }

        if ($powerpoint) {
            try {
                $powerpoint.Quit()
            }
            catch {
            }

            Release-ComObject -Object $powerpoint
        }
    }
}

$sourceItem = Get-Item -LiteralPath $InputPath
$sourcePath = $sourceItem.FullName
$targetPath = [System.IO.Path]::GetFullPath($OutputPath)

$targetDir = Split-Path -Parent $targetPath
if (-not [string]::IsNullOrWhiteSpace($targetDir)) {
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
}

$ext = $sourceItem.Extension.ToLowerInvariant()
$wordExt = @('.docx')
$powerExt = @('.pptx')

try {
    try {
        if ($wordExt -contains $ext) {
            Export-WithWord -SourcePath $sourcePath -TargetPath $targetPath
        }
        elseif ($powerExt -contains $ext) {
            Export-WithPowerPoint -SourcePath $sourcePath -TargetPath $targetPath
        }
        else {
            throw "Unsupported audit extension: $ext"
        }
    }
    catch {
        if (Test-BenignOfficeDisconnect -ErrorRecord $_ -TargetPath $targetPath) {
            Write-Warning "Office COM disconnected after export, but the PDF was already created: $TargetPath"
        }
        else {
            throw
        }
    }
}
finally {
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
