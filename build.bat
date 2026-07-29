@echo off
SETLOCAL EnableDelayedExpansion

echo ===================================================
echo   [TCA] Starting Automated Nuitka Production Build  
echo ===================================================

:: 1. Navigate to the project root directory safely
cd /d "D:\repos\Torn - Company Data Puller"

:: 🟢 CONFIGURATION: Set your custom output directory path here
:: (It will be automatically created by Nuitka if it doesn't exist yet)
set "BUILD_DESTINATION=D:\repos\Torn - Company Data Puller\builds"

:: 2. Activate your isolated virtual environment layout
call .\.venv\Scripts\activate.bat

:: 3. Run the version manager and capture the output stream
set "APP_VERSION="
for /f "tokens=*" %%i in ('".\.venv\Scripts\python.exe" bump_version.py') do (
    set "APP_VERSION=%%i"
)

:: Safety Check: If the variable is empty, stop before the Nuitka block
if "%APP_VERSION%"=="" (
    echo [ERROR] The version bumper script failed to output a version number.
    pause
    exit /b
)

echo [+] Current Build Incremented To: %APP_VERSION%
echo [+] Output Target Destination: %BUILD_DESTINATION%
echo [+] Compiling source layers via C backend optimization...

:: 4. Execute the absolute production Nuitka configuration block
nuitka --onefile --remove-output --follow-imports --windows-console-mode=disable --windows-icon-from-ico="D:\repos\Torn - Company Data Puller\TCA-v3.ico" --output-dir="%BUILD_DESTINATION%" --output-filename="TCA-v%APP_VERSION%.exe" --company-name="sharpsplinter [315311]" --file-version="%APP_VERSION%" --product-version="%APP_VERSION%" --product-name="TCA" --file-description="Assistant for Torn.com that allows one the ability to easily see/manage daily company data" --include-data-files="D:\repos\Torn - Company Data Puller\client_secret.json=client_secret.json" --include-data-files="D:\repos\Torn - Company Data Puller\legal\TCA_Privacy_Policy.docx=legal/TCA_Privacy_Policy.docx" --include-data-files="D:\repos\Torn - Company Data Puller\legal\TCA_Terms_of_Service.docx=legal/TCA_Terms_of_Service.docx" --enable-plugin=tk-inter main.py

echo ===================================================
echo   [SUCCESS] TCA-v%APP_VERSION%.exe saved to destination!
echo ===================================================
explorer.exe "%BUILD_DESTINATION%"


pause