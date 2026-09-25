# Canvas-Syncer

A script that lets you sync your local files with those under the "Files" tab of your course sites on [Canvas](https://umich.instructure.com).

This forked version contains bug fixes, modifications to user input and output, as well as a logging function to facilitate futher debugging.

## Usage

**The following bash script would install the latest release version of the original BoYanZh/Canvas-Syncer from `pip`, instead of the version on this repository.**

```bash
canvassyncer
```

Then follow the onscreen guide to provide your access token, course name or number, local file storage location, etc.

*Note:*
1. `courseCode` should be something like `VG100`, `ECE4530J`
2. `courseID` should be an integer. Check the canvas link of the course. e.g. `courseID = 7` for <https://jicanvas.com/courses/7>.

### Optional arguments

```text
  -h, --help            show this help message and exit
  -r                    recreate config file
  -y                    confirm all prompts
  --no-subfolder        do not create a course code named subfolder when synchronizing files
  -p PATH, --path PATH  appoint config file path
  -c CONNECTION, --connection CONNECTION
                        max connection count with server
  -x PROXY, --proxy PROXY
                        download proxy
  -V, --version         show program's version number and exit
  -d, --debug           show debug information
  --no-keep-older-version
                        do not keep older version
```

### Canvas Access Token Generation

Open Your Canvas-Account-Approved Integrations-New Access Token

Or it can be easily achieved with <https://github.com/BoYanZh/JI-Auth> if you are a UM-SJTU-JI student.


## Futher Contributions

Please feel free to create issues and pull requests.

> TODO: Compile source code into executable and publish it on either `pip` or the release page of this repository.
