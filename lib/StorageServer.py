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
import hashlib
import inspect
import os
import socket
import string
import sys
import time

import xbmc

try:
    import sqlite
except:
    pass

try:
    import sqlite3
except:
    pass


class StorageServer():
    def __init__(self, table=None, timeout=24, instance=False):
        self.version = u"2.5.4"
        self.plugin = u"StorageClient-{0}".format(self.version)
        self.instance = instance
        self.die = False

        if hasattr(sys.modules["__main__"], "dbg"):
            self.dbg = sys.modules["__main__"].dbg
        else:
            self.dbg = False

        if hasattr(sys.modules["__main__"], "dbglevel"):
            self.dbglevel = sys.modules["__main__"].dbglevel
        else:
            self.dbglevel = 3

        if hasattr(sys.modules["__main__"], "xbmc"):
            self.xbmc = sys.modules["__main__"].xbmc
        else:
            import xbmc
            self.xbmc = xbmc

        if hasattr(sys.modules["__main__"], "xbmcvfs"):
            self.xbmcvfs = sys.modules["__main__"].xbmcvfs
        else:
            import xbmcvfs
            self.xbmcvfs = xbmcvfs

        if hasattr(sys.modules["__main__"], "xbmcaddon"):
            self.xbmcaddon = sys.modules["__main__"].xbmcaddon
        else:
            import xbmcaddon
            self.xbmcaddon = xbmcaddon

        self.settings = self.xbmcaddon.Addon(id='script.common.plugin.cache')
        self.language = self.settings.getLocalizedString

        self.path = self.xbmc.translatePath('special://temp/')
        if isinstance(self.path, bytes):
            self.path = self.path.decode('utf-8')
        if not self.xbmcvfs.exists(self.path):
            self._log(u"Making path structure: {0}".format(self.path))
            self.xbmcvfs.mkdir(self.path)
        self.path = os.path.join(self.path, 'commoncache.db')

        self.socket = ""
        self.clientsocket = False
        self.sql2 = False
        self.sql3 = False
        self.abortRequested = False
        self.daemon_start_time = time.time()
        if self.instance:
            self.idle = int(self.settings.getSetting("timeout"))
        else:
            self.idle = 3

        self.platform = sys.platform
        self.modules = sys.modules
        self.network_buffer_size = 4096

        if isinstance(table, str) and len(table) > 0:
            self.table = ''.join(c for c in table if
                                 c in "{0}{1}".format(string.ascii_letters,
                                                      string.digits))
            self._log("Setting table to : {0}".format(self.table))
        elif table != False:  # noqa E712
            self._log("No table defined")

        self.setCacheTimeout(timeout)

    def _startDB(self):
        try:
            if "sqlite3" in self.modules:
                self.sql3 = True
                self._log("sql3 - {0}".format(self.path), 2)
                self.conn = sqlite3.connect(self.path, check_same_thread=False)
            elif "sqlite" in self.modules:
                self.sql2 = True
                self._log("sql2 - {0}".format(self.path), 2)
                self.conn = sqlite.connect(self.path)
            else:
                self._log("Error, no sql found")
                return False

            self.curs = self.conn.cursor()
            return True
        except Exception as e:
            self._log("Exception: {0}".format(repr(e)))
            self.xbmcvfs.delete(self.path)
            return False

    def _aborting(self):
        if self.instance:
            if self.die:
                return True
        else:
            return self.xbmc.abortRequested
        return False

    def _usePosixSockets(self):
        if self.platform in ["win32", 'win10'] or any(
                xbmc.getCondVisibility('system.platform.android'),
                xbmc.getCondVisibility('system.platform.ios'),
                xbmc.getCondVisibility('system.platform.tvos')):
            return False
        else:
            return True

    def _sock_init(self, check_stale=False):
        self._log("", 2)
        if not self.socket or check_stale:
            self._log("Checking", 4)

            if self._usePosixSockets():
                self._log("POSIX", 4)
                self.socket = os.path.join(
                    self.xbmc.translatePath('special://temp/').decode("utf-8"),
                    'commoncache.socket')
                if self.xbmcvfs.exists(self.socket) and check_stale:
                    self._log(
                        "Deleting stale socket file : {0}".format(self.socket))
                    self.xbmcvfs.delete(self.socket)
            else:
                self._log("Non-POSIX", 4)
                port = self.settings.getSetting("port")
                self.socket = ("127.0.0.1", int(port))

        self._log("Done: {0}".format(repr(self.socket)), 2)

    def _recieveData(self):
        self._log("", 3)
        data = self._recv(self.clientsocket)
        self._log("received data: {0}".format(repr(data)), 4)

        try:
            data = eval(data)
        except:
            self._log("Couldn't evaluate message : {0}".format(repr(data)))
            data = {"action": "stop"}

        self._log("Done, got data: {0} - {1}".format(str(len(data)),
                                                     str(repr(data))[0:50]), 3)
        return data

    def _runCommand(self, data):
        self._log("", 3)
        res = ""
        if data["action"] == "get":
            res = self._sqlGet(data["table"], data["name"])
        elif data["action"] == "get_multi":
            res = self._sqlGetMulti(data["table"], data["name"], data["items"])
        elif data["action"] == "set_multi":
            res = self._sqlSetMulti(data["table"], data["name"], data["data"])
        elif data["action"] == "set":
            res = self._sqlSet(data["table"], data["name"], data["data"])
        elif data["action"] == "del":
            res = self._sqlDel(data["table"], data["name"])
        elif data["action"] == "lock":
            res = self._lock(data["table"], data["name"])
        elif data["action"] == "unlock":
            res = self._unlock(data["table"], data["name"])

        if len(res) > 0:
            self._log(
                "Got response: {0} - {1}".format(str(len(res)),
                                                 str(repr(res))[0:50]), 3)
            self._send(self.clientsocket, repr(res))

        self._log("Done", 3)

    def _showMessage(self, heading, message):
        self._log("{0} - {1}".format(repr(type(heading)), repr(type(message))))
        duration = 10 * 1000
        self.xbmc.executebuiltin(
            (u'XBMC.Notification("{0}", "{1}", {2})'.format(
                heading, message, duration)))

    def run(self):
        self.plugin = "StorageServer-{0}".format(self.version)
        self.xbmc.log(
            "{0} Storage Server starting {1}".format(self.plugin, self.path))
        self._sock_init(True)

        if not self._startDB():
            self._startDB()

        if self._usePosixSockets():
            sock = socket.socket(socket.AF_UNIX)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            sock.bind(self.socket)
        except Exception as e:
            self._log("Exception: {0}".format(repr(e)))
            self._showMessage(self.language(100), self.language(200))

            return False

        sock.listen(1)
        sock.setblocking(0)

        idle_since = time.time()
        waiting = 0
        while not self._aborting():
            if waiting == 0:
                self._log("accepting", 3)
                waiting = 1
            try:
                (self.clientsocket, address) = sock.accept()
                if waiting == 2:
                    self._log("Waking up, slept for {0} seconds.".format(
                        int(time.time() - idle_since)))
                waiting = 0
            except socket.error as e:
                if e.errno == 11 or e.errno == 10035 or e.errno == 35:
                    # There has to be a better way to accomplish this.
                    if idle_since + self.idle < time.time():
                        if self.instance:
                            self.die = True
                        if waiting == 1:
                            self._log(
                                "Idle for {0} seconds. Going to sleep. "
                                "zzzzzzzz ".format(self.idle))
                        time.sleep(0.5)
                        waiting = 2
                    continue
            except:
                pass

            if waiting:
                self._log("Continue : {0}".format(repr(waiting)), 3)
                continue

            data = self._recieveData()
            self._runCommand(data)
            idle_since = time.time()

            self._log("Done")

        self._log("Closing down")
        sock.close()

        if self._usePosixSockets():
            if self.xbmcvfs.exists(self.socket):
                self._log("Deleting socket file")
                self.xbmcvfs.delete(self.socket)
        self.xbmc.log("{0} Closed down".format(self.plugin))

    def _recv(self, sock):
        data = b"   "
        idle = True

        self._log(u"", 3)
        i = 0
        start = time.time()
        while data[len(data) - 2:] != u"\r\n".encode('utf-8') or not idle:
            self._log('Not idle')
            try:
                if idle:
                    recv_buffer = sock.recv(self.network_buffer_size)
                    if isinstance(recv_buffer, str):
                        recv_buffer = recv_buffer.encode('utf-8')
                    idle = False
                    i += 1
                    self._log(u"got data  : {0} - {1} - {2}"
                              u"+ {3} | {4}".format(
                                  str(i), repr(idle), str(len(data)),
                                  str(len(recv_buffer)),
                                  repr(recv_buffer)[len(recv_buffer) - 5:]), 4)
                    data += recv_buffer
                    start = time.time()
                elif not idle:
                    if data[len(data) - 2:] == u"\r\n".encode('utf-8'):
                        sock.send(u"COMPLETE\r\n{0}".format(
                            " " * (15 - len(u"COMPLETE\r\n"))).encode('utf-8'))
                        idle = True
                        self._log(u"sent COMPLETE {0}".format(str(i)), 4)

                    elif len(recv_buffer) > 0:
                        sock.send(u"ACK\r\n{0}".format(
                            (u" " * (15 - len(u"ACK\r\n")))).encode('utf-8'))
                        idle = True
                        self._log(u"sent ACK {0}".format(str(i)), 4)
                    recv_buffer = ""
                    self._log(u"status {0} - {1}".format(repr(not idle), repr(
                        data[len(data) - 2:] != u"\r\n".encode('utf-8'))), 3)

            except socket.error as e:
                if e.errno not in [10035, 35]:
                    self._log(u"Except error! {0}".format(repr(e)))

                if e.errno in [22]:  # We can't fix this.
                    return ""

                if start + 10 < time.time():
                    self._log(u"over time", 2)
                    break

        self._log(u"done", 3)
        return data.strip()

    def _send(self, sock, data):
        idle = True
        status = ""
        self._log(u"{0} - {1}".format(str(len(data)), repr(data)[0:20]), 3)
        i = 0
        start = time.time()
        while len(data) > 0 or not idle:
            send_buffer = b" "
            try:
                if idle:
                    if len(data) > self.network_buffer_size:
                        send_buffer = data[:self.network_buffer_size]
                    else:
                        send_buffer = data + "\r\n"
                    if isinstance(send_buffer, str):
                        send_buffer = send_buffer.encode('utf-8')
                    self.xbmc.log(str(type(send_buffer)),
                                  self.xbmc.LOGNOTICE)
                    result = sock.send(send_buffer)
                    i += 1
                    idle = False
                    start = time.time()
                elif not idle:
                    status = b""
                    while status.find(u"COMPLETE\r\n".encode(
                            'utf-8')) == -1 and status.find(
                            u"ACK\r\n".encode('utf-8')) == -1:
                        status = sock.recv(15)
                        i -= 1

                    idle = True
                    if len(data) > self.network_buffer_size:
                        data = data[self.network_buffer_size:]
                    else:
                        data = ""

                    self._log(u"Got response {0} - {1} == {2} "
                              u"| {3} - {4}".format(
                                  str(i), str(result),
                                  str(len(send_buffer)),
                                  str(len(data)),
                                  repr(send_buffer)[
                                      len(send_buffer) - 5:]), 3)

            except socket.error as e:
                self._log(u"Except error {0}".format(repr(e)))
                if all([e.errno != 10035, e.errno != 35, e.errno != 107,
                       e.errno != 32]):
                    self._log(u"Except error {0}".format(repr(e)))
                    if start + 10 < time.time():
                        self._log(u"Over time", 2)
                        break
        self._log(u"Done", 3)
        return status.find(u"COMPLETE\r\n".encode('utf-8')) > -1

    def _lock(self, table, name):  # This is NOT atomic
        self._log(name, 1)
        locked = True
        curlock = self._sqlGet(table, name)
        if curlock.strip():
            if float(curlock) < self.daemon_start_time:
                self._log(u"removing stale lock.")
                self._sqlExecute(
                    "DELETE FROM {0} WHERE name = %s".format(table), (name,))
                self.conn.commit()
                locked = False
        else:
            locked = False

        if not locked:
            self._sqlExecute(
                "INSERT INTO {0} VALUES ( %s , %s )".format(table),
                (name, time.time()))
            self.conn.commit()
            self._log(u"locked: {0}".format(name.decode('utf8', 'ignore')))

            return "true"

        self._log(u"failed for : {0}".format(name.decode('utf8', 'ignore')), 1)
        return "false"

    def _unlock(self, table, name):
        self._log(name, 1)

        self._checkTable(table)
        self._sqlExecute("DELETE FROM {0} WHERE name = %s".format(table),
                         (name,))

        self.conn.commit()
        self._log(u"done", 1)
        return "true"

    def _sqlSetMulti(self, table, pre, inp_data):
        self._log(pre, 1)
        self._checkTable(table)
        for name in inp_data:
            if self._sqlGet(table, "{0}{1}".format(pre, name)).strip():
                self._log(
                    u"Update (0): ".format(pre, name.decode('utf8', 'ignore')),
                    3)
                self._sqlExecute(
                    "UPDATE {0} SET data = %s WHERE name = %s".format(table),
                    (inp_data[name], "{0}{1}".format(pre, name)))
            else:
                self._log(
                    u"Insert : {0}".format(pre, name.decode('utf8', 'ignore')),
                    3)
                self._sqlExecute(
                    "INSERT INTO {0} VALUES ( %s , %s )".format(table),
                    ("{0}{1}".format(pre, name), inp_data[name]))

        self.conn.commit()
        self._log(u"Done", 3)
        return ""

    def _sqlGetMulti(self, table, pre, items):
        self._log(pre, 1)

        self._checkTable(table)
        ret_val = []
        for name in items:
            self._log('{0}{1}'.format(pre, name), 3)
            self._sqlExecute(
                "SELECT data FROM {0} WHERE name = %s".format(table),
                ("{0}{1}".format(pre, name)))

            result = ""
            for row in self.curs:
                self._log(u"Adding : {0}".format(str(repr(row[0]))[0:20]), 3)
                result = row[0]
            ret_val += [result]

        self._log(u"Returning : {0}".format(repr(ret_val)), 2)
        return ret_val

    def _sqlSet(self, table, name, data):
        self._log('{0}{1}'.format(name, str(repr(data))[0:20]), 2)

        self._checkTable(table)
        if self._sqlGet(table, name).strip():
            self._log(u"Update : {0}".format(data), 3)
            self._sqlExecute(
                "UPDATE {0} SET data = %s WHERE name = %s".format(table),
                (data, name))
        else:
            self._log(u"Insert : {0}".format(data), 3)
            self._sqlExecute(
                "INSERT INTO {0} VALUES ( %s , %s )".format(table),
                (name, data))

        self.conn.commit()
        self._log(u"Done", 2)
        return ""

    def _sqlDel(self, table, name):
        self._log('{0} - {1}'.format(name, table), 1)

        self._checkTable(table)

        self._sqlExecute("DELETE FROM {0} WHERE name LIKE %s".format(table),
                         name)
        self.conn.commit()
        self._log(u"done", 1)
        return "true"

    def _sqlGet(self, table, name):
        self._log("{0} - {1}".format(name, table), 2)

        self._checkTable(table)
        self._sqlExecute("SELECT data FROM {0} WHERE name = %s".format(table),
                         name)

        for row in self.curs:
            self._log(u"Returning :  {0}".format(str(repr(row[0]))[0:20]), 3)
            return row[0]

        self._log(u"Returning empty", 3)
        return " "

    def _sqlExecute(self, sql, data):
        try:
            self._log("{0} - {1}".format(repr(sql), repr(data)), 5)
            if self.sql2:
                self.curs.execute(sql, data)
            elif self.sql3:
                sql = sql.replace("%s", "?")
                if isinstance(data, tuple):
                    self.curs.execute(sql, data)
                else:
                    self.curs.execute(sql, (data,))
        except sqlite3.DatabaseError as e:
            if (self.xbmcvfs.exists(self.path) and (
                    str(e).find("file is encrypted") > -1 or str(e).find(
                    "not a database") > -1)):
                self._log(u"Deleting broken database file")
                self.xbmcvfs.delete(self.path)
                self._startDB()
            else:
                self._log(
                    u"Database error, but database NOT deleted: {0}".format(
                        repr(e)))
        except:
            self._log(u"Uncaught exception")

    def _checkTable(self, table):
        try:
            self.curs.execute(
                "create table {0} (name text unique, data text)".format(table))
            self.conn.commit()
            self._log(u"Created new table")
        except:
            self._log(u"Passed", 5)
            pass

    def _evaluate(self, data):
        try:
            data = eval(data)  # Test json.loads vs eval
            return data
        except:
            self._log(u"Couldn't evaluate message : {0}".format(repr(data)))
            return ""

    def _generateKey(self, funct, *args):
        self._log(u"", 5)
        name = repr(funct)
        if name.find(" of ") > -1:
            name = name[name.find("method") + 7:name.find(" of ")]
        elif name.find(" at ") > -1:
            name = name[name.find("function") + 9:name.find(" at ")]

        keyhash = hashlib.md5()
        for params in args:
            if isinstance(params, dict):
                for key in sorted(params.keys()):
                    if key not in ["new_results_function"]:
                        keyhash.update("'{0}'='{1}'".format(key, params[key]))
            elif isinstance(params, list):
                keyhash.update(",".join(["{0}".format(el for el in params)]))
            else:
                try:
                    keyhash.update(params)
                except:
                    keyhash.update(str(params))

        name += "|{0}|".format(keyhash.hexdigest())

        self._log(u"Done: {0}".format(repr(name)), 5)
        return name

    def _getCache(self, name, cache):
        self._log(u"")
        if name in cache:
            if "timeout" not in cache[name]:
                cache[name]["timeout"] = 3600

            if cache[name]["timestamp"] > time.time() - (
                    cache[name]["timeout"]):
                self._log(u"Done, found cache : {0}".format(
                    name.decode('utf8', 'ignore')))
                return cache[name]["res"]
            else:
                self._log(u"Deleting old cache : {0}".format(
                    name.decode('utf8', 'ignore')), 1)
                del(cache[name])

        self._log(u"Done")
        return False

    def _setCache(self, cache, name, ret_val):
        self._log(u"")
        if len(ret_val) > 0:
            if not isinstance(cache, dict):
                cache = {}
            cache[name] = {"timestamp": time.time(),
                           "timeout": self.timeout,
                           "res": ret_val}
            self._log(u"Saving cache: {0}{1}".format(name, str(
                repr(cache[name]["res"]))[0:50]), 1)
            self.set("cache{0}".format(name), repr(cache))
        self._log(u"Done")
        return ret_val


# EXTERNAL FUNCTIONS #
    soccon = False
    table = False

    def cacheFunction(self, funct=False, *args):
        self._log(u"function : {0} - table_name: {1}".format(repr(funct),
                                                             repr(self.table)))
        if funct and self.table:
            name = self._generateKey(funct, *args)
            cache = self.get("cache{0}".format(name))

            if cache.strip() == "":
                cache = {}
            else:
                cache = self._evaluate(cache)

            ret_val = self._getCache(name, cache)

            if not ret_val:
                self._log(
                    u"Running: {0}".format(name.decode('utf8', 'ignore')))
                ret_val = funct(*args)
                self._setCache(cache, name, ret_val)

            if ret_val:
                self._log(u"Returning result: {0}".format(str(len(ret_val))))
                self._log(ret_val, 4)
                return ret_val
            else:
                self._log(
                    u"Returning []. Got result: {0}".format(repr(ret_val)))
                return []

        self._log(u"Error")
        return []

    def cacheDelete(self, name):
        self._log(name, 1)
        if self._connect() and self.table:
            temp = repr({"action": "del", "table": self.table,
                         "name": "cache{0}".format(name)})
            self._send(self.soccon, temp)
            res = self._recv(self.soccon)
            self._log(u"GOT {0}".format(repr(res)), 3)

    def cacheClean(self, empty=False):
        self._log(u"")
        if self.table:
            cache = self.get("cache{0}".format(self.table))

            try:
                cache = self._evaluate(cache)
            except:
                self._log(
                    u"Couldn't evaluate message : {0}".format(repr(cache)))

            self._log(u"Cache : {0}".format(repr(cache)), 5)
            if cache:
                new_cache = {}
                for item in cache:
                    if (cache[item]["timestamp"] > time.time() - (
                            3600)) and not empty:
                        new_cache[item] = cache[item]
                    else:
                        self._log(u"Deleting: {0}".format(
                            item.decode('utf8', 'ignore')))

                self.set("cache", repr(new_cache))
                return True

        return False

    def lock(self, name):
        self._log(name, 1)
        self._log(self.table, 1)

        if self._connect() and self.table:
            data = repr({"action": "lock", "table": self.table, "name": name})
            self._send(self.soccon, data)
            res = self._recv(self.soccon)
            if res:
                res = self._evaluate(res)

                if res == "true":
                    self._log(u"Done : {0}".format(res.strip()), 1)
                    return True

        self._log(u"Failed", 1)
        return False

    def unlock(self, name):
        self._log(name, 1)

        if self._connect() and self.table:
            data = repr(
                {"action": "unlock", "table": self.table, "name": name})
            self._send(self.soccon, data)
            res = self._recv(self.soccon)
            if res:
                res = self._evaluate(res)

                if res == "true":
                    self._log(u"Done: {0}".format(res.strip()), 1)
                    return True

        self._log(u"Failed", 1)
        return False

    def _connect(self):
        self._log("", 3)
        self._sock_init()

        if self._usePosixSockets():
            self.soccon = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        else:
            self.soccon = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        connected = False
        try:
            self.soccon.connect(self.socket)
            connected = True
        except socket.error as e:
            if e.errno in [111]:
                self._log(u"StorageServer isn't running")
            else:
                self._log(u"Exception: {0}".format(repr(e)))
                self._log(u"Exception: {0}".format(repr(self.socket)))

        return connected

    def setMulti(self, name, data):
        self._log(name, 1)
        if self._connect() and self.table:
            temp = repr(
                {"action": "set_multi", "table": self.table, "name": name,
                 "data": data})
            res = self._send(self.soccon, temp)
            self._log(u"GOT {0}".format(repr(res)), 3)

    def getMulti(self, name, items):
        self._log(name, 1)
        if self._connect() and self.table:
            self._send(self.soccon, repr(
                {"action": "get_multi", "table": self.table, "name": name,
                 "items": items}))
            self._log(u"Receive", 3)
            res = self._recv(self.soccon)

            self._log(u"res : {0}".format(str(len(res))), 3)
            if res:
                res = self._evaluate(res)

                if res == " ":  # We return " " as nothing.
                    return ""
                else:
                    return res

        return ""

    def delete(self, name):
        self._log(name, 1)
        if self._connect() and self.table:
            temp = repr({"action": "del", "table": self.table, "name": name})
            self._send(self.soccon, temp)
            res = self._recv(self.soccon)
            self._log(u"GOT {0}".format(repr(res)), 3)

    def set(self, name, data):
        self._log(name, 1)
        if self._connect() and self.table:
            temp = repr({"action": "set", "table": self.table, "name": name,
                         "data": data})
            res = self._send(self.soccon, temp)
            self._log(u"GOT {0}".format(repr(res)), 3)

    def get(self, name):
        self._log(name, 1)
        if self._connect() and self.table:
            self._send(self.soccon, repr(
                {"action": "get", "table": self.table, "name": name}))
            self._log(u"Receive", 3)
            res = self._recv(self.soccon)

            self._log(u"res : {0}".format(str(len(res))), 3)
            if res:
                res = self._evaluate(res)
                return res.strip()  # We return " " as nothing. Strip it out.

        return ""

    def setCacheTimeout(self, timeout):
        self.timeout = float(timeout) * 3600

    def _log(self, description, level=0):
        if self.dbg and self.dbglevel > level:
            self.xbmc.log(u"[{0}] {1} : {2}".format(self.plugin, repr(
                inspect.stack()[1][3]), repr(description)),
                          self.xbmc.LOGNOTICE)


# Check if this module should be run in instance mode or not.
__workersByName = {}


def run_async(func, *args, **kwargs):
    from threading import Thread
    worker = Thread(target=func, args=args, kwargs=kwargs)
    __workersByName[worker.getName()] = worker
    worker.start()
    return worker


def checkInstanceMode():
    if hasattr(sys.modules["__main__"], "xbmcaddon"):
        xbmcaddon = sys.modules["__main__"].xbmcaddon
    else:
        import xbmcaddon

    settings = xbmcaddon.Addon(id='script.common.plugin.cache')
    if settings.getSetting("autostart") == "false":
        s = StorageServer(table=False, instance=True)
        xbmc.log(u" StorageServer Module loaded RUN(instance only)")

        xbmc.log('{0} Starting server'.format(s.plugin))

        run_async(s.run)
        return True
    else:
        return False


checkInstanceMode()
