'''
    Cache service for XBMC
    Copyright (C) 2010-2011 Tobias Ussing And Henrik Mosgaard Jensen

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
    Version 0.8
'''
import xbmc

import xbmcaddon

settings = xbmcaddon.Addon(id='script.common.plugin.cache')
dbg = settings.getSetting("debug") == "true"
dbglevel = 3


def run():
    from lib import StorageServer
    s = StorageServer.StorageServer(False)
    xbmc.log("StorageServer Module loaded RUN")
    xbmc.log("{0} Starting server".format(s.plugin))
    s.run()
    return True


if __name__ == "__main__":
    if settings.getSetting("autostart") == "true":
        run()
