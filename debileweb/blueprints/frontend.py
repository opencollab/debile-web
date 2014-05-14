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
from debian.debian_support import Version

from debile.master.utils import Session
from debile.master.orm import (Person, Builder, Suite, Check,
                               Group, GroupSuite, Source, Maintainer, Job)

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
    session = Session()

    groups = session.query(Group).order_by(
        Group.name.asc(),
    ).all()
    builders = session.query(Builder).order_by(
        Builder.name.asc(),
    ).all()

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
        info['maintainer_link'] = "/user/%s" % builder.maintainer.email
        jobs = session.query(Job).filter(
            Job.assigned_at != None,
            Job.finished_at == None,
            Job.builder == builder,
        ).order_by(
            Job.assigned_at.desc(),
        ).all()
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

    info = {}
    info['unfinished_sources'] = session.query(Source).filter(
        Source.jobs.any(Job.failed.is_(None)),
    ).count()
    info['queued_sources'] = session.query(Source).filter(
        Source.jobs.any(
            ~Job.depedencies.any() &
            (Job.dose_report == None) &
            (Job.assigned_at == None) &
            (Job.finished_at == None) &
            Job.failed.is_(None)
        ),
    ).count()
    info['unbuilt_sources'] = session.query(Source).filter(
        Source.jobs.any(
            Job.check.has(Check.build == True) &
            ~Job.built_binaries.any()
        ),
    ).count()
    info['failed_sources'] = session.query(Source).filter(
        Source.jobs.any(Job.failed.is_(True)),
    ).count()

    info['unfinished_jobs'] = session.query(Job).filter(
        Job.failed.is_(None),
    ).count()
    info['queued_jobs'] = session.query(Job).filter(
        ~Job.depedencies.any(),
        Job.dose_report == None,
        Job.assigned_at == None,
        Job.finished_at == None,
        Job.failed.is_(None),
    ).count()
    info['unbuilt_jobs'] = session.query(Job).filter(
        Job.check.has(Check.build == True),
        ~Job.built_binaries.any(),
    ).count()
    info['failed_jobs'] = session.query(Job).filter(
        Job.failed.is_(True),
    ).count()

    form = SearchPackageForm()

    session.rollback()
    session.close()

    return render_template('index.html', **{
        "groups_info": groups_info,
        "builders_info": builders_info,
        "info": info,
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
    if request.path == "/maintainer/search/":
        return redirect('/maintainer/' + request.form['maintainer'] + '/')
    if request.path == "/source/search/":
        return redirect('/source/' + request.form['source'] + '/')

    page = int(page)
    session = Session()

    if request.path.startswith("/maintainer/"):
        desc = "Search results for maintainer '%s'" % search
        query = session.query(Source).filter(
            Source.maintainers.any(
                Maintainer.name.contains(search) |
                Maintainer.email.contains(search)
            ),
        ).order_by(
            Source.name.asc(),
            Source.uploaded_at.desc(),
        )
    elif request.path.startswith("/source/"):
        desc = "Search results for source package '%s'" % search
        query = session.query(Source).filter(
            Source.name.contains(search),
        ).order_by(
            Source.name.asc(),
            Source.uploaded_at.desc(),
        )
    elif prefix == "recent":
        desc = "All recently uploaded source packages."
        query = session.query(Source).order_by(
            Source.uploaded_at.desc(),
        )
    elif prefix == "unfinished":
        desc = "All source packages with unfinished jobs."
        query = session.query(Source).filter(
            Source.jobs.any(Job.failed.is_(None)),
        ).order_by(
            Source.name.asc(),
            Source.uploaded_at.desc(),
        )
    elif prefix == "queued":
        desc = "All source packages with jobs in the queue."
        query = session.query(Source).filter(
            Source.jobs.any(
                ~Job.depedencies.any() &
                (Job.dose_report == None) &
                (Job.assigned_at == None) &
                (Job.finished_at == None) &
                Job.failed.is_(None)
            ),
        ).order_by(
            Source.name.asc(),
            Source.uploaded_at.desc(),
        )
    elif prefix == "unbuilt":
        desc = "All source packages with unbuilt build jobs."
        query = session.query(Source).filter(
            Source.jobs.any(
                Job.check.has(Check.build == True) &
                ~Job.built_binaries.any()
            ),
        ).order_by(
            Source.name.asc(),
            Source.uploaded_at.desc(),
        )
    elif prefix == "failed":
        desc = "All source packages with failed jobs."
        query = session.query(Source).filter(
            Source.jobs.any(Job.failed.is_(True)),
        ).order_by(
            Source.name.asc(),
            Source.uploaded_at.desc(),
        )
    elif prefix == "l":
        desc = "All sources for packages beginning with 'l'"
        query = session.query(Source).filter(
            Source.name.startswith("l"),
            ~Source.name.startswith("lib"),
        ).order_by(
            Source.name.asc(),
            Source.uploaded_at.desc(),
        )
    else:
        desc = "All sources for packages beginning with '%s'" % prefix
        query = session.query(Source).filter(
            Source.name.startswith(prefix),
        ).order_by(
            Source.name.asc(),
            Source.uploaded_at.desc(),
        )

    source_count = query.count()
    sources = query.offset(page * ENTRIES_PER_LIST_PAGE).limit(ENTRIES_PER_LIST_PAGE).all()

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

    session.rollback()
    session.close()

    return render_template('sources.html', **{
        "info": info,
        "sources_info": sources_info,
    })


@frontend.route("/jobs/")
@frontend.route("/jobs/<prefix>/")
@frontend.route("/jobs/<prefix>/<page>/")
def jobs(prefix="recent", page=0):
    page = int(page)
    session = Session()

    if prefix == "recent":
        desc = "All recently uploaded jobs."
        query = session.query(Job).join(Job.source).order_by(
            Source.uploaded_at.desc(),
            Job.id.asc(),
        )
    elif prefix == "unfinished":
        desc = "All unfinished jobs."
        query = session.query(Job).join(Job.source).filter(
            Job.failed.is_(None),
        ).order_by(
            Source.name.asc(),
            Source.uploaded_at.desc(),
            Job.id.asc(),
        )
    elif prefix == "queued":
        desc = "All jobs in the queue."
        query = session.query(Job).join(Job.source).join(Job.check).filter(
            Job.dose_report == None,
            ~Job.depedencies.any(),
            Job.assigned_at == None,
            Job.finished_at == None,
            Job.failed.is_(None),
        ).order_by(
            Job.assigned_count.asc(),
            Check.build.desc(),
            Source.uploaded_at.asc(),
        )
    elif prefix == "unbuilt":
        desc = "All unbuilt build jobs."
        query = session.query(Job).join(Job.source).filter(
            Job.check.has(Check.build == True),
            ~Job.built_binaries.any(),
        ).order_by(
            Source.name.asc(),
            Source.uploaded_at.desc(),
            Job.id.asc(),
        )
    elif prefix == "failed":
        desc = "All failed jobs."
        query = session.query(Job).join(Job.source).filter(
            Job.failed.is_(True),
        ).order_by(
            Source.name.asc(),
            Source.uploaded_at.desc(),
            Job.id.asc(),
        )
    elif prefix == "l":
        desc = "All jobs for packages beginning with 'l'"
        query = session.query(Job).join(Job.source).filter(
            Source.name.startswith("l"),
            ~Source.name.startswith("lib"),
        ).order_by(
            Source.name.asc(),
            Source.uploaded_at.desc(),
            Job.id.asc(),
        )
    else:
        desc = "All jobs for packages beginning with '%s'" % prefix
        query = session.query(Job).join(Job.source).filter(
            Source.name.startswith(prefix),
        ).order_by(
            Source.name.asc(),
            Source.uploaded_at.desc(),
            Job.id.asc(),
        )

    job_count = query.count()
    jobs = query.offset(page * ENTRIES_PER_LIST_PAGE).limit(ENTRIES_PER_LIST_PAGE).all()

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

    session.rollback()
    session.close()

    return render_template('jobs.html', **{
        "info": info,
        "jobs_info": jobs_info,
    })


@frontend.route("/group/<name>/")
@frontend.route("/group/<name>/<page>/")
def group(name, page=0):
    page = int(page)
    session = Session()

    group = session.query(Group).filter(
        Group.name == name,
    ).one()

    source_count = session.query(Source).filter(
        GroupSuite.group == group,
    ).count()
    sources = session.query(Source).filter(
        GroupSuite.group == group,
    ).order_by(
        Source.uploaded_at.desc(),
    ).offset(page * ENTRIES_PER_PAGE).limit(ENTRIES_PER_PAGE).all()

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

    session.rollback()
    session.close()

    return render_template('group.html', **{
        "group": group,
        "info": info,
        "sources_info": sources_info,
    })


@frontend.route("/builder/<name>")
@frontend.route("/builder/<name>/<page>")
def builder(name, page=0):
    page = int(page)
    session = Session()

    builder = session.query(Builder).filter(
        Builder.name == name,
    ).one()

    job_count = session.query(Job).filter(
        Job.builder == builder,
    ).count()
    jobs = session.query(Job).filter(
        Job.builder == builder,
    ).order_by(
        Job.assigned_at.desc(),
    ).offset(page * ENTRIES_PER_PAGE).limit(ENTRIES_PER_PAGE).all()

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

    session.rollback()
    session.close()

    return render_template('builder.html', **{
        "builder": builder,
        "jobs_info": jobs_info,
        "info": info,
    })


@frontend.route("/user/<email>/")
@frontend.route("/user/<email>/<page>/")
def user(email, page=0):
    page = int(page)
    session = Session()

    user = session.query(Person).filter(
        Person.email == email,
    ).one()

    groups = session.query(Group).filter(
        Group.maintainer == user,
    ).order_by(
        Group.name.asc(),
    ).all()

    builders = session.query(Builder).filter(
        Builder.maintainer == user,
    ).order_by(
        Builder.name.asc(),
    ).all()

    source_count = session.query(Source).filter(
        Source.uploader == user,
    ).count()
    sources = session.query(Source).filter(
        Source.uploader == user,
    ).order_by(
        Source.uploaded_at.desc(),
    ).offset(page * ENTRIES_PER_PAGE).limit(ENTRIES_PER_PAGE).all()

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
        jobs = session.query(Job).filter(
            Job.assigned_at != None,
            Job.finished_at == None,
            Job.builder == builder,
        ).order_by(
            Job.assigned_at.desc(),
        ).all()
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

    session.rollback()
    session.close()

    return render_template('user.html', **{
        "user": user,
        "info": info,
        "groups_info": groups_info,
        "builders_info": builders_info,
        "sources_info": sources_info,
    })


@frontend.route("/source/<group_name>/<package_name>/<suite_or_version>/")
def source(group_name, package_name, suite_or_version):
    session = Session()

    source = session.query(Source).filter(
        Group.name == group_name,
        Source.name == package_name,
        (Source.version == suite_or_version) |
        (Suite.name == suite_or_version),
    ).order_by(
        Source.uploaded_at.desc()
    ).first()

    if not source:
        return render_template('source-not-found.html', **{
            "group_name": group_name,
            "package_name": package_name,
            "suite_or_version": suite_or_version,
        })

    # Find all versions of this package
    versions = session.query(
        Source.version,
    ).filter(
        Group.name == group_name,
        Source.name == package_name,
    )
    versions = sorted([x[0] for x in versions], key=Version, reverse=True)

    versions_info = []
    if len(versions) > 1:
        for version in versions:
            href = "/source/%s/%s/%s" % \
                (group_name, package_name, version)
            versions_info.append((version, href))

    jobs = session.query(Job).filter(
        Job.source == source,
    ).order_by(
        Job.id.asc(),
    ).all()

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
    info['uploader_link'] = "/user/%s" % source.uploader.email

    session.rollback()
    session.close()

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
    session = Session()

    job = session.query(Job).get(job_id)

    info = {}
    info['group_link'] = "/group/%s" % job.group.name
    info['source_link'] = '/source/%s/%s/%s' % \
        (job.group.name, job.source.name, job.source.version)
    info['binary_link'] = '/job/%s/%s/%s/%d' % \
        (job.group.name, job.binary.name, job.binary.version, job.binary.build_job_id) \
        if (job.binary and job.binary.build_job_id) else None
    info['builder_link'] = "/builder/%s" % job.builder.name if job.builder else None

    info['job_runtime'] = None
    if job.finished_at and job.assigned_at:
        time_diff = job.finished_at - job.assigned_at
        hours, remainder = divmod(time_diff.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        info['job_runtime'] = '%dh %02dm %02ds' % \
            (hours, minutes, seconds)

    deps_info = []
    for dep in job.depedencies:
        depinfo = {}
        depinfo['job'] = dep
        depinfo['job_link'] = "/job/%s/%s/%s/%s" % \
            (dep.group.name, dep.source.name, dep.source.version, dep.id)
        depinfo['source_link'] = "/source/%s/%s/%s" % \
            (dep.group.name, dep.source.name, dep.source.version)
        deps_info.append(depinfo)

    results_info = []
    for result in job.results:
        try:
            resultinfo = {}
            resultinfo['result'] = result
            resultinfo['dud_name'] = None
            resultinfo['log_name'] = None
            resultinfo['firehose_name'] = None
            resultinfo['files'] = []
            for fname in os.listdir(result.path):
                if fname.endswith(".dud"):
                    resultinfo['dud_name'] = fname
                elif fname.endswith(".log"):
                    resultinfo['log_name'] = fname
                elif fname.endswith(".firehose.xml"):
                    resultinfo['firehose_name'] = fname
                else:
                    resultinfo['files'] += [fname]
            results_info.append(resultinfo)
        except OSError:
            pass

    session.rollback()
    session.close()

    return render_template('job.html', **{
        "job": job,
        "info": info,
        "deps_info": deps_info,
        "results_info": results_info,
    })


@frontend.route('/_search_source')
def search_source():
    search = request.args.get('search[term]')
    session = Session()

    query = session.query(
        Source.name,
    ).filter(
        Source.name.startswith(search),
    ).group_by(
        Source.name,
    ).limit(10).all()
    result = [r[0] for r in query]

    session.rollback()
    session.close()

    return jsonify(result)


@frontend.route('/_search_maintainer')
def search_maintainer():
    search = request.args.get('search[term]')
    session = Session()

    query = session.query(
        Maintainer.name,
        Maintainer.email,
    ).filter(
        Maintainer.name.startswith(search) |
        Maintainer.email.startswith(search),
    ).group_by(
        Maintainer.name,
        Maintainer.email,
    ).limit(10).all()
    result = [r[0] if r[0].startswith(search) else r[1] for r in query]

    session.rollback()
    session.close()

    return jsonify(result)


@frontend.route('/about')
def about():
    return render_template('about.html')
