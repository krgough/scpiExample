# scpiProject

This project contains modules that send scpi commands to instruments e.g. 34465a multimeter.
Use it to set up measuremnts and log the data.

scpi_module_34465a Module contains the specific code to send test commands to tha device.
It includes current and voltage consumption test methods we can use to over extended periods.

See the device manual for details of the commands used.

Install the package:

pip3 install git+https://github.com/krgough/scpiExample.git

(or clone the git hub repo)

Using the package:

In a python script import and the package as follows:

from scpi_project import scpi_module_34465a
scpi_module_34465a.main()
