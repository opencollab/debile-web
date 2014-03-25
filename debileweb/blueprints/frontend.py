# Copyright (c) 2012 Paul Tagliamonte <paultag@debian.org>
# Copyright (c) 2013 Leo Cavaille <leo@cavaille.net>
# Copyright (c) 2013 Sylvestre Ledru <sylvestre@debian.org>
# Copyright (c) 2014 Jon Severinsson <jon@severinsson.net>
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

from flask import Blueprint, render_template, request, redirect
from flask.ext.jsonpify import jsonify
from sqlalchemy.orm import joinedload

from debile.master.utils import make_session
from debile.master.orm import (Person, Builder, Suite, Component, Arch, Check,
                               Group, GroupSuite, Source, Maintainer, Binary,
                               Job, JobDependencies, Result)

from debileweb.blueprints.forms import SearchPackageForm
from debileweb.blueprints.consts import PREFIXES, ENTRIES_PER_PAGE, ENTRIES_PER_LIST_PAGE

from datetime import datetime
from humanize import naturaltime
import os

frontend = Blueprint('frontend', __name__, template_folder='templates')


@frontend.app_template_filter('ago')
def ago_display(when):
    if when is None:
        return "never"
    td = datetime.utcnow() - when
    return naturaltime(td)


@frontend.route("/")
def index():
    session = make_session()

    groups = session.query(Group)\
        .order_by(Group.name.asc())\
        .all()
    builders = session.query(Builder)\
        .order_by(Builder.name.asc())\
        .all()

    groups_info = []
    for group in groups:
        info = {}
        info['group'] = group
        info['group_link'] = "/group/%s" % group.name
        info['maintainer_link'] = "/user/%s" % group.maintainer.email
        groups_info.append(info)

    builders_info = []
    for builder in builders:
        info = {}
        info['builder'] = builder
        info['builder_link'] = "/builder/%s" % builder.name
        info['maintainer_link'] = "/user/%s" % group.maintainer.email
        jobs = session.query(Job).join(Source)\
            .filter(Job.assigned_at != None)\
            .filter(Job.finished_at == None)\
            .filter(Job.builder == builder)\
            .order_by(Job.id.desc())\
            .all()
        jobs_info = []
        for job in jobs:
            jobinfo = {}
            jobinfo['job'] = job
            jobinfo['job_link'] = "/job/%s/%s/%s/%s" % \
                (job.group.name, job.source.name, job.source.version, job.id)
            jobinfo['source_link'] = "/source/%s/%s/%s" % \
                (job.group.name, job.source.name, job.source.version)
            jobs_info.append(jobinfo)
        info['jobs_info'] = jobs_info
        builders_info.append(info)

    pending_jobs = session.query(Job)\
        .filter(Job.assigned_at == None)\
        .count()
    form = SearchPackageForm()

    return render_template('index.html', **{
        "groups_info": groups_info,
        "builders_info": builders_info,
        "pending_jobs": pending_jobs,
        "prefixes": PREFIXES,
        "form": form
    })


@frontend.route("/maintainer/<search>/", methods=['POST', 'GET'])
@frontend.route("/maintainer/<search>/<page>")
@frontend.route("/source/<search>/", methods=['POST', 'GET'])
@frontend.route("/source/<search>/<page>")
@frontend.route("/sources/")
@frontend.route("/sources/<prefix>/")
@frontend.route("/sources/<prefix>/<page>/")
def sources(search="", prefix="recent", page=0):
    page = int(page)
    session = make_session()

    if request.path == "/maintainer/search/":
        return redirect('/maintainer/' + request.form['maintainer'] + '/')
    if request.path == "/source/search/":
        return redirect('/source/' + request.form['source'] + '/')

    if request.path.startswith("/maintainer/"):
        source_count = session.query(Source)\
            .count()
        desc = "Search results for maintainer '%s'" % search
        source_count = session.query(Source)\
            .filter(Source.maintainers.any(Maintainer.name.contains(search) |
                                           Maintainer.email.contains(search)))\
            .count()
        sources = session.query(Source)\
            .filter(Source.maintainers.any(Maintainer.name.contains(search) |
                                           Maintainer.email.contains(search)))\
            .order_by(Source.name.asc(), Source.id.desc())\
            .offset(page * ENTRIES_PER_LIST_PAGE)\
            .limit(ENTRIES_PER_LIST_PAGE)\
            .all()
    elif request.path.startswith("/source/"):
        desc = "Search results for source '%s'" % search
        source_count = session.query(Source)\
            .filter(Source.name.contains(search))\
            .count()
        sources = session.query(Source)\
            .filter(Source.name.contains(search))\
            .order_by(Source.name.asc(), Source.id.desc())\
            .offset(page * ENTRIES_PER_LIST_PAGE)\
            .limit(ENTRIES_PER_LIST_PAGE)\
            .all()
    elif prefix == "recent":
        desc = "All recent sources."
        source_count = session.query(Source).count()
        sources = session.query(Source)\
            .order_by(Source.id.desc())\
            .offset(page * ENTRIES_PER_LIST_PAGE)\
            .limit(ENTRIES_PER_LIST_PAGE)\
            .all()
    elif prefix == "incomplete":
        desc = "All incomplete sources."
        source_count = session.query(Source)\
            .filter(Source.jobs.any(Job.finished_at == None))\
            .count()
        sources = session.query(Source)\
            .filter(Source.jobs.any(Job.finished_at == None))\
            .order_by(Source.name.asc(), Source.id.desc())\
            .offset(page * ENTRIES_PER_LIST_PAGE)\
            .limit(ENTRIES_PER_LIST_PAGE)\
            .all()
    elif prefix == "l":
        desc = "All sources for packages beginning with 'l'"
        source_count = session.query(Source)\
            .filter(Source.name.startswith("l"))\
            .filter(~Source.name.startswith("lib"))\
            .count()
        sources = session.query(Source)\
            .filter(Source.name.startswith("l"))\
            .filter(~Source.name.startswith("lib"))\
            .order_by(Source.name.asc(), Source.id.desc())\
            .offset(page * ENTRIES_PER_LIST_PAGE)\
            .limit(ENTRIES_PER_LIST_PAGE)\
            .all()
    else:
        desc = "All sources for packages beginning with '%s'" % prefix
        source_count = session.query(Source)\
            .filter(Source.name.startswith(prefix))\
            .count()
        sources = session.query(Source)\
            .filter(Source.name.startswith(prefix))\
            .order_by(Source.name.asc(), Source.id.desc())\
            .offset(page * ENTRIES_PER_LIST_PAGE)\
            .limit(ENTRIES_PER_LIST_PAGE)\
            .all()

    sources_info = []
    for source in sources:
        info = {}
        info['source'] = source
        info['source_link'] = "/source/%s/%s/%s" % \
            (source.group.name, source.name, source.version)
        info['group_link'] = "/group/%s" % source.group.name
        info['uploader_link'] = "/user/%s" % source.uploader.email
        sources_info.append(info)

    info = {}
    info['desc'] = desc
    info['prev_link'] = "/sources/%s/%d" % (prefix, page-1) \
        if page > 0 else None
    info['next_link'] = "/sources/%s/%d" % (prefix, page+1) \
        if source_count > (page+1) * ENTRIES_PER_LIST_PAGE else None

    return render_template('sources.html', **{
        "info": info,
        "sources_info": sources_info,
    })


@frontend.route("/jobs/")
@frontend.route("/jobs/<prefix>/")
@frontend.route("/jobs/<prefix>/<page>/")
def jobs(prefix="recent", page=0):
    page = int(page)
    session = make_session()

    if prefix == "recent":
        desc = "All recent jobs."
        job_count = session.query(Job).count()
        jobs = session.query(Job).join(Source).join(Check)\
            .order_by(Source.id.desc())\
            .offset(page * ENTRIES_PER_LIST_PAGE)\
            .limit(ENTRIES_PER_LIST_PAGE)\
            .all()
    elif prefix == "incomplete":
        desc = "All incomplete jobs."
        job_count = session.query(Job)\
            .filter(Job.finished_at == None)\
            .count()
        jobs = session.query(Job).join(Source).join(Check)\
            .filter(Job.finished_at == None)\
            .order_by(Source.name.asc(), Source.id.desc(),
                      Check.build.desc(), Check.id.asc(),
                      Job.id.asc())\
            .offset(page * ENTRIES_PER_LIST_PAGE)\
            .limit(ENTRIES_PER_LIST_PAGE)\
            .all()
    elif prefix == "l":
        desc = "All jobs for packages beginning with 'l'"
        job_count = session.query(Job).join(Source)\
            .filter(Source.name.startswith("l"))\
            .filter(~Source.name.startswith("lib"))\
            .count()
        jobs = session.query(Job).join(Source).join(Check)\
            .filter(Source.name.startswith("l"))\
            .filter(~Source.name.startswith("lib"))\
            .order_by(Source.name.asc(), Source.id.desc(),
                      Check.build.desc(), Check.id.asc(),
                      Job.id.asc())\
            .offset(page * ENTRIES_PER_LIST_PAGE)\
            .limit(ENTRIES_PER_LIST_PAGE)\
            .all()
    else:
        desc = "All jobs for packages beginning with '%s'" % prefix
        job_count = session.query(Job).join(Source)\
            .filter(Source.name.startswith(prefix))\
            .count()
        jobs = session.query(Job).join(Source).join(Check)\
            .filter(Source.name.startswith(prefix))\
            .order_by(Source.name.asc(), Source.id.desc(),
                      Check.build.desc(), Check.id.asc(),
                      Job.id.asc())\
            .offset(page * ENTRIES_PER_LIST_PAGE)\
            .limit(ENTRIES_PER_LIST_PAGE)\
            .all()

    jobs_info = []
    for job in jobs:
        info = {}
        info['job'] = job
        info['job_link'] = "/job/%s/%s/%s/%s" % \
            (job.group.name, job.source.name, job.source.version, job.id)
        info['source_link'] = "/source/%s/%s/%s" % \
            (job.group.name, job.source.name, job.source.version)
        info['group_link'] = "/group/%s" % job.group.name
        info['builder_link'] = "/builder/%s" % job.builder.name \
            if job.builder else None
        jobs_info.append(info)

    info = {}
    info['desc'] = desc
    info['prev_link'] = "/jobs/%s/%d" % (prefix, page-1) \
        if page > 0 else None
    info['next_link'] = "/jobs/%s/%d" % (prefix, page+1) \
        if job_count > (page+1) * ENTRIES_PER_LIST_PAGE else None

    return render_template('jobs.html', **{
        "info": info,
        "jobs_info": jobs_info,
    })


@frontend.route("/group/<name>/")
@frontend.route("/group/<name>/<page>/")
def group(name, page=0):
    page = int(page)
    session = make_session()

    group = session.query(Group)\
        .filter(Group.name == name)\
        .one()

    source_count = session.query(Source)\
        .filter(Source.group == group)\
        .count()
    sources = session.query(Source)\
        .filter(Source.group == group)\
        .order_by(Source.id.desc())\
        .offset(page * ENTRIES_PER_PAGE)\
        .limit(ENTRIES_PER_PAGE)\
        .all()

    sources_info = []
    for source in sources:
        info = {}
        info['source'] = source
        info['source_link'] = "/source/%s/%s/%s" % \
            (source.group.name, source.name, source.version)
        info['uploader_link'] = "/user/%s" % source.uploader.email
        sources_info.append(info)

    info = {}
    info['maintainer_link'] = "/user/%s" % group.maintainer.email
    info['prev_link'] = "/group/%s/%d" % (group.name, page-1) \
        if page > 0 else None
    info['next_link'] = "/group/%s/%d" % (group.name, page+1) \
        if source_count > (page+1) * ENTRIES_PER_PAGE else None

    return render_template('group.html', **{
        "group": group,
        "info": info,
        "sources_info": sources_info,
    })


@frontend.route("/builder/<name>")
@frontend.route("/builder/<name>/<page>")
def builder(name, page=0):
    page = int(page)
    session = make_session()

    builder = session.query(Builder)\
        .filter(Builder.name == name)\
        .one()

    job_count = session.query(Job).filter(Job.builder == builder).count()
    jobs = session.query(Job).join(Source)\
        .filter(Job.builder == builder)\
        .order_by(Job.id.desc())\
        .offset(page * ENTRIES_PER_PAGE)\
        .limit(ENTRIES_PER_PAGE)\
        .all()

    jobs_info = []
    for job in jobs:
        info = {}
        info['job'] = job
        info['job_link'] = "/job/%s/%s/%s/%s" % \
            (job.group.name, job.source.name, job.source.version, job.id)
        info['source_link'] = "/source/%s/%s/%s" % \
            (job.group.name, job.source.name, job.source.version)
        info['group_link'] = "/group/%s" % job.group.name
        jobs_info.append(info)

    info = {}
    info['maintainer_link'] = "/user/%s" % builder.maintainer.email
    info['prev_link'] = "/builder/%s/%d" % (builder.name, page-1) \
        if page > 0 else None
    info['next_link'] = "/builder/%s/%d" % (builder.name, page+1) \
        if job_count > (page+1) * ENTRIES_PER_PAGE else None

    return render_template('builder.html', **{
        "builder": builder,
        "jobs_info": jobs_info,
        "info": info,
    })


@frontend.route("/user/<email>/")
@frontend.route("/user/<email>/<page>/")
def user(email, page=0):
    page = int(page)
    session = make_session()

    user = session.query(Person)\
        .filter(Person.email == email)\
        .one()

    groups = session.query(Group)\
        .filter(Group.maintainer == user)\
        .order_by(Group.name.asc())\
        .all()

    builders = session.query(Builder)\
        .filter(Builder.maintainer == user)\
        .order_by(Builder.name.asc())\
        .all()

    source_count = session.query(Source)\
        .filter(Source.uploader == user)\
        .count()
    sources = session.query(Source)\
        .filter(Source.uploader == user)\
        .order_by(Source.id.desc())\
        .offset(page * ENTRIES_PER_PAGE)\
        .limit(ENTRIES_PER_PAGE)\
        .all()

    groups_info = []
    for group in groups:
        info = {}
        info['group'] = group
        info['group_link'] = "/group/%s" % group.name
        groups_info.append(info)

    builders_info = []
    for builder in builders:
        info = {}
        info['builder'] = builder
        info['builder_link'] = "/builder/%s" % builder.name
        jobs = session.query(Job).join(Source)\
            .filter(Job.assigned_at != None)\
            .filter(Job.finished_at == None)\
            .filter(Job.builder == builder)\
            .order_by(Job.id.desc())\
            .all()
        jobs_info = []
        for job in jobs:
            jobinfo = {}
            jobinfo['job'] = job
            jobinfo['job_link'] = "/job/%s/%s/%s/%s" % \
                (job.group.name, job.source.name, job.source.version, job.id)
            jobinfo['source_link'] = "/source/%s/%s/%s" % \
                (job.group.name, job.source.name, job.source.version)
            jobs_info.append(jobinfo)
        info['jobs_info'] = jobs_info
        builders_info.append(info)

    sources_info = []
    for source in sources:
        info = {}
        info['source'] = source
        info['source_link'] = "/source/%s/%s/%s" % \
            (source.group.name, source.name, source.version)
        info['group_link'] = "/group/%s" % source.group.name
        sources_info.append(info)

    info = {}
    info['prev_link'] = "/user/%s/%d" % (user.email, page-1) \
        if page > 0 else None
    info['next_link'] = "/user/%s/%d" % (user.email, page+1) \
        if source_count > (page+1) * ENTRIES_PER_PAGE else None

    return render_template('user.html', **{
        "user": user,
        "info": info,
        "groups_info": groups_info,
        "builders_info": builders_info,
        "sources_info": sources_info,
    })


@frontend.route("/source/<group_name>/<package_name>/<suite_or_version>/")
def source(group_name, package_name, suite_or_version):
    session = make_session()

    source = session.query(Source)\
        .filter(Group.name == group_name)\
        .filter(Source.name == package_name)\
        .filter((Source.version == suite_or_version) |
                (Suite.name == suite_or_version))\
        .order_by(Source.id.desc()).first()

    if not source:
        return render_template('source-not-found.html', **{
            "group_name": group_name,
            "package_name": package_name,
            "suite_or_version": suite_or_version,
        })

    # Find all versions of this package
    versions = session.query(Source.version)\
        .filter(Group.name == group_name)\
        .filter(Source.name == package_name)\
        .order_by(Source.id.desc()).all()

    versions_info = []
    if len(versions) > 1:
        for version in versions:
            href = "/source/%s/%s/%s" % \
                (group_name, package_name, version)
            versions_info.append((version, href))

    jobs = session.query(Job).join(Check)\
        .filter(Job.source == source)\
        .order_by(Check.build.desc(), Check.id.asc(), Job.id.asc())\
        .all()

    total = len(jobs)
    unfinished = 0
    jobs_info = []
    for job in jobs:
        info = {}
        info['job'] = job
        info['job_link'] = '/job/%s/%s/%s/%d' % \
            (group_name, package_name, source.version, job.id)
        info['builder_link'] = '/builder/%s' % job.builder.name \
            if job.builder else None
        if job.finished_at is None:
            unfinished += 1
            info['status'] = 'running' if job.assigned_at else 'pending'
        else:
            info['status'] = 'finished'

        jobs_info.append(info)

    info = {}
    info["job_status"] = (total, unfinished)
    info['group_link'] = "/group/%s" % source.group.name
    info['uploader_link'] = "/user/%s" % source.uploader.name

    return render_template('source.html', **{
        "source": source,
        "info": info,
        "versions_info": versions_info,
        "jobs_info": jobs_info,
    })


@frontend.route("/job/<job_id>/")
@frontend.route("/job/<group_name>/<package_name>/<package_version>/<job_id>/")
def job(job_id, group_name="", package_name="", package_version="", version=""):
    job_id = int(job_id)
    session = make_session()

    job = session.query(Job).get(job_id)

    time_diff = job.finished_at - job.assigned_at
    hours, remainder = divmod(time_diff.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)

    info = {}
    info['job_runtime'] = '%dh %02dm %02ds' % \
        (hours, minutes, seconds)
    info['source_link'] = '/source/%s/%s/%s' % \
        (job.group.name, job.source.name, job.source.version)
    info['binary_link'] = '/job/%s/%s/%s/%d' % \
        (job.group.name, job.binary.name, job.binary.version, job.binary.build_job_id) if job.binary else None
    info['builder_link'] = "/builder/%s" % job.builder.name

    info['dud_name'] = "%d.dud" % job.id
    info['log_name'] = "%d.log" % job.id
    info['firehose_name'] = "%d.firehose.xml" % job.id
    special_files = [info['dud_name'], info['log_name'], info['firehose_name']]
    try:
        info['files'] = sorted([x for x in os.listdir(job.files_path) if x not in special_files])
    except OSError:
        info['files'] = []

    return render_template('job.html', **{
        "job": job,
        "info": info,
    })


@frontend.route('/_search_source')
def search_source():
    search = request.args.get('search[term]')
    session = make_session()
    query = session.query(Source.name)\
        .filter(Source.name.startswith(search))\
        .group_by(Source.name).limit(10)
    result = [r[0] for r in query]
    return jsonify(result)


@frontend.route('/_search_maintainer')
def search_maintainer():
    search = request.args.get('search[term]')
    session = make_session()
    query = session.query(Maintainer.name, Maintainer.email)\
        .filter(Maintainer.name.startswith(search) |
                Maintainer.email.startswith(search))\
        .group_by(Maintainer.name, Maintainer.email).limit(10)
    result = [r[0] if r[0].startswith(search) else r[1] for r in query]
    return jsonify(result)


@frontend.route('/about')
def about():
    return render_template('about.html')
