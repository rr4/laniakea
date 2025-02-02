/*
 * Copyright (C) 2016-2017 Matthias Klumpp <matthias@tenstral.net>
 *
 * Licensed under the GNU Lesser General Public License Version 3
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation, either version 3 of the license, or
 * (at your option) any later version.
 *
 * This software is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with this software.  If not, see <http://www.gnu.org/licenses/>.
 */

module lknative.tagfile;
@safe:

import std.string : startsWith, indexOf, chompPrefix, strip, split, splitLines;
import std.array : appender, empty;
import std.conv : to;
import std.path : buildPath;
import std.typecons : Flag, Yes;

import lknative.utils : splitStrip;
import lknative.compressed;
import lknative.repository.types;

/**
 * Parser for Debian's RFC2822-style metadata.
 */
final class TagFile
{

private:
    string[] content;
    uint pos;
    string[string] currentBlock;

    string _fname;
    bool _isEmpty;

public:

    this () @trusted
    {
        currentBlock.clear ();
        _isEmpty = true;
    }

    /**
     * Check if the file is empty, return true in that case.
     */
    @property
    bool isEmpty () const
    {
        return this._isEmpty;
    }

    void open (string fname, Flag!"compressed" compressed = Yes.compressed) @trusted
    {
        _fname = fname;

        if (compressed) {
            auto data = decompressFileToString (fname);
            load (data);
        } else {
            import std.stdio : File, readln;

            auto f = File (fname, "r");
            auto data = appender!string;
            string line;
            while ((line = f.readln ()) !is null)
                data ~= line;
            load (data.data);
        }
    }

    @property
    string fname () const { return _fname; }

    void load (string data)
    {
        content = data.splitLines ();
        pos = 0;
        readCurrentBlockData ();

        _isEmpty = content.length <= 1;
    }

    void first () {
        pos = 0;
    }

    private void readCurrentBlockData () @trusted
    {
        currentBlock.clear ();
        immutable clen = content.length;

        for (auto i = pos; i < clen; i++) {
            if (content[i] == "")
                break;

            // check whether we are in a multiline value field, and just skip forward in that case
            if (startsWith (content[i], " "))
                continue;

            immutable separatorIndex = indexOf (content[i], ':');
            if (separatorIndex <= 0)
                continue; // this is no field

            auto fieldName = content[i][0..separatorIndex];
            auto fdata = content[i][separatorIndex+1..$];

            if ((i+1 >= clen)
                || (!startsWith (content[i+1], " "))) {
                    // we have a single-line field
                    currentBlock[fieldName] = fdata.strip ();
            } else {
                // we have a multi-line field
                auto fdata_ml = appender!string ();
                fdata_ml ~= fdata.strip ();
                for (auto j = i+1; j < clen; j++) {
                    auto slice = chompPrefix (content[j], " ");
                    if (slice == content[j])
                        break;

                    if (fdata_ml.data == "") {
                        fdata_ml = appender!string ();
                        fdata_ml ~= slice;
                    } else {
                        fdata_ml ~= "\n";
                        fdata_ml ~= slice;
                    }
                }

                currentBlock[fieldName] = fdata_ml.data;
            }
        }
    }

    bool nextSection () @trusted
    {
        bool breakNext = false;
        immutable clen = content.length;
        currentBlock.clear ();

        if (pos >= clen)
            return false;

        uint i;
        for (i = pos; i < clen; i++) {
            if (content[i] == "") {
                pos = i + 1;
                breakNext = true;
            } else if (breakNext) {
                break;
            }
        }

        // check if we reached the end of this file
        if (i == clen)
            pos = cast(uint) clen;

        if (pos >= clen)
            return false;

        readCurrentBlockData ();
        return true;
    }

    string readField (string name, string defaultValue = null) pure @trusted
    {
        auto dataP = name in currentBlock;
        if (dataP is null)
            return defaultValue; // we found nothing
        else
            return *dataP;
    }
}

/**
 * Parse a "Package-List" field and return its information in
 * PackageInfo data structures.
 * See https://www.debian.org/doc/debian-policy/ch-controlfields.html#s-f-Package-List
 */
public PackageInfo[] parsePackageListString (const string pkgListRaw, const string defaultVersion = null) pure @safe
{
    import std.string : splitLines;

    auto res = appender!(PackageInfo[]);
    res.reserve (3);
    foreach (ref line; pkgListRaw.splitLines) {
        auto parts = line.strip.split (" ");
        if (parts.length < 4)
            continue;

        PackageInfo pi;
        pi.name = parts[0];
        pi.ver = defaultVersion;
        pi.debType = debTypeFromString (parts[1]);
        pi.section = parts[2];
        pi.priority = packagePriorityFromString (parts[3]);

        if (parts.length > 4) {
            // we have additional data
            auto rawVals = parts[4].split (" ");
            foreach (ref v; rawVals) {
                if (v.startsWith ("arch=")) {
                    // handle architectures
                    pi.architectures = v[5..$].split (",");
                }
            }
        }

        res ~= pi;
    }

    return res.data;
}

public ArchiveFile[] parseChecksumsList (string dataRaw, string baseDir = null)
{
    auto files = appender!(ArchiveFile[]);
    files.reserve (3);
    foreach (ref fileRaw; dataRaw.split ('\n')) {
        auto parts = fileRaw.strip.splitStrip (" "); // f43923ace1c558ad9f9fa88eb3f1764a8c0379013aafbc682a35769449fe8955 2455 0ad_0.0.20-1.dsc
        if (parts.length != 3)
            continue;

        ArchiveFile file;
        file.sha256sum = parts[0];
        file.size = to!size_t (parts[1]);
        if (baseDir.empty)
            file.fname = parts[2];
        else
            file.fname = buildPath (baseDir, parts[2]);

        files ~= file;
    }
    return files.data;
}
