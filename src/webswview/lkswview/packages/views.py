# -*- coding: utf-8 -*-
#
# Copyright (C) 2018-2019 Matthias Klumpp <matthias@tenstral.net>
#
# Licensed under the GNU Lesser General Public License Version 3
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the license, or
# (at your option) any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this software.  If not, see <http://www.gnu.org/licenses/>.

import math
import humanize
from flask import current_app, Blueprint, render_template, abort, url_for
from laniakea.db import session_scope, BinaryPackage, SourcePackage, ArchiveSuite, \
    Job, JobStatus, JobResult, SparkWorker, ArchiveArchitecture
from sqlalchemy.orm import undefer, joinedload
from laniakea.utils import get_dir_shorthand_for_uuid
from ..extensions import cache
from ..utils import humanized_timediff, is_uuid

packages = Blueprint('packages',
                     __name__,
                     url_prefix='/package')


@cache.memoize(1800)
def make_linked_dependency(suite_name, depstr):
    if not depstr:
        return depstr
    deps = [d.strip() for d in depstr.split('|')]

    dep_urls = []
    for dep in deps:
        parts = dep.split(' ', 1)
        pkgname = parts[0]
        versioning = parts[1].strip() if len(parts) > 1 else ''

        url = '<a href="{url}">{pkgname}</a> {versioning}'.format(url=url_for('packages.bin_package_details', suite_name=suite_name, name=pkgname),
                                                                  pkgname=pkgname,
                                                                  versioning=versioning)
        dep_urls.append(url)

    return ' | '.join(dep_urls)


@cache.memoize(3600)
def all_architectures(session):
    return session.query(ArchiveArchitecture).all()


@packages.route('/bin/<suite_name>/<name>')
@cache.cached(timeout=120)
def bin_package_details(suite_name, name):
    with session_scope() as session:
        bpkgs = session.query(BinaryPackage) \
                       .options(joinedload(BinaryPackage.architecture)) \
                       .options(joinedload(BinaryPackage.pkg_file)) \
                       .options(undefer(BinaryPackage.version)) \
                       .filter(BinaryPackage.name == name) \
                       .filter(BinaryPackage.suites.any(ArchiveSuite.name == suite_name)) \
                       .order_by(BinaryPackage.version.desc()).all()
        if not bpkgs:
            abort(404)

        suites = [s[0] for s in session.query(ArchiveSuite.name.distinct())
                                       .filter(ArchiveSuite.bin_packages.any(BinaryPackage.name == name))
                                       .all()]

        architectures = set()
        bpkg_rep = bpkgs[0]  # the first package is always the most recent one
        for bpkg in bpkgs:
            architectures.add(bpkg.architecture)
        if not bpkg_rep:
            abort(404)

        return render_template('packages/bin_details.html',
                               pkg=bpkg_rep,
                               pkgs_all=bpkgs,
                               pkg_suite_name=suite_name,
                               suites=suites,
                               architectures=architectures,
                               naturalsize=humanize.naturalsize,
                               make_linked_dependency=make_linked_dependency)


@packages.route('/src/<suite_name>/<name>')
@cache.cached(timeout=120)
def src_package_details(suite_name, name):
    with session_scope() as session:
        spkgs = session.query(SourcePackage) \
                       .options(undefer(SourcePackage.version)) \
                       .filter(SourcePackage.suites.any(ArchiveSuite.name == suite_name)) \
                       .filter(SourcePackage.name == name) \
                       .order_by(SourcePackage.version.desc()) \
                       .all()
        if not spkgs:
            abort(404)

        suites = [s[0] for s in session.query(ArchiveSuite.name.distinct())
                                       .filter(ArchiveSuite.src_packages.any(SourcePackage.name == name))
                                       .all()]
        spkg_rep = spkgs[0]  # the first package is always the most recent one

        return render_template('packages/src_details.html',
                               pkg=spkg_rep,
                               pkgs_all=spkgs,
                               pkg_suite_name=suite_name,
                               suites=suites,
                               make_linked_dependency=make_linked_dependency)


@packages.route('/builds/<name>/<int:page>')
@cache.cached(timeout=50)
def builds_list(name, page):
    with session_scope() as session:
        spkg = session.query(SourcePackage) \
            .filter(SourcePackage.name == name) \
            .order_by(SourcePackage.version.desc()) \
            .first()
        if not spkg:
            abort(404)

        jobs_per_page = 20
        jobs_total = session.query(Job) \
            .filter(Job.trigger == spkg.source_uuid) \
            .order_by(Job.time_created.desc()) \
            .count()
        page_count = math.ceil(jobs_total / jobs_per_page)

        jobs_list = session.query(Job) \
                           .filter(Job.trigger == spkg.source_uuid) \
                           .order_by(Job.time_created.desc()) \
                           .slice((page - 1) * jobs_per_page, page * jobs_per_page) \
                           .all()

        # create by-architecture view on jobs
        jobs_arch = {}
        for arch in all_architectures(session):
            jobs_arch[arch.name] = []
        for j in jobs_list:
            if j.architecture not in jobs_arch:
                jobs_arch[j.architecture] = []
            jobs_arch[j.architecture].append(j)

        return render_template('packages/builds_list.html',
                               JobStatus=JobStatus,
                               humanized_timediff=humanized_timediff,
                               pkg=spkg,
                               jobs_arch=jobs_arch,
                               jobs_per_page=jobs_per_page,
                               jobs_total=jobs_total,
                               current_page=page,
                               page_count=page_count)


@packages.route('/builds/job/<uuid>')
@cache.cached(timeout=5)
def build_details(uuid):
    if not is_uuid(uuid):
        abort(404)

    with session_scope() as session:
        job = session.query(Job).filter(Job.uuid == uuid).one_or_none()
        if not job:
            abort(404)

        worker = session.query(SparkWorker).filter(SparkWorker.uuid == job.worker).one_or_none()

        log_url = None
        if job.result == JobResult.SUCCESS or job.result == JobResult.FAILURE:
            log_url = current_app.config['LOG_STORAGE_URL'] + '/' + get_dir_shorthand_for_uuid(job.uuid) + '/' + str(job.uuid) + '.log'

        spkg = session.query(SourcePackage) \
            .filter(SourcePackage.source_uuid == job.trigger) \
            .filter(SourcePackage.version == job.version) \
            .one_or_none()
        if not spkg:
            abort(404)

        suite_name = 'unknown'
        if job.data:
            suite_name = job.data.get('suite')

        return render_template('packages/build_details.html',
                               humanized_timediff=humanized_timediff,
                               JobStatus=JobStatus,
                               JobResult=JobResult,
                               job=job,
                               worker=worker,
                               spkg=spkg,
                               suite_name=suite_name,
                               log_url=log_url)
