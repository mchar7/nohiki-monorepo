#!/bin/sh
# Refuse destructive Git commands inside Nohiki working checkouts.

real_git=${NOHIKI_GIT_REAL:-@git@}
if [ "$real_git" = '@git@' ]; then
    real_git=$(command -p -v git 2>/dev/null) || {
        printf 'git-guard: unable to locate git\n' >&2
        exit 127
    }
fi

should_refuse() {
    probe_dir=$PWD
    probe_git_dir=
    probe_work_tree=
    have_git_dir=0
    have_work_tree=0
    subcommand=

    while [ "$#" -gt 0 ]; do
        case $1 in
            -C)
                [ "$#" -ge 2 ] || return 1
                case $2 in
                    /*) probe_dir=$2 ;;
                    '') ;;
                    *) probe_dir=$probe_dir/$2 ;;
                esac
                shift 2
                ;;
            -C?*)
                value=${1#-C}
                case $value in
                    /*) probe_dir=$value ;;
                    *) probe_dir=$probe_dir/$value ;;
                esac
                shift
                ;;
            --git-dir | --work-tree)
                option=$1
                [ "$#" -ge 2 ] || return 1
                value=$2
                case $value in
                    /*) ;;
                    *) value=$probe_dir/$value ;;
                esac
                if [ "$option" = --git-dir ]; then
                    probe_git_dir=$value
                    have_git_dir=1
                else
                    probe_work_tree=$value
                    have_work_tree=1
                fi
                shift 2
                ;;
            --git-dir=* | --work-tree=*)
                option=${1%%=*}
                value=${1#*=}
                case $value in
                    /*) ;;
                    *) value=$probe_dir/$value ;;
                esac
                if [ "$option" = --git-dir ]; then
                    probe_git_dir=$value
                    have_git_dir=1
                else
                    probe_work_tree=$value
                    have_work_tree=1
                fi
                shift
                ;;
            -c | --config-env)
                [ "$#" -ge 2 ] || return 1
                shift 2
                ;;
            --)
                shift
                [ "$#" -gt 0 ] || return 1
                subcommand=$1
                shift
                break
                ;;
            -*) shift ;;
            *)
                subcommand=$1
                shift
                break
                ;;
        esac
    done

    case $subcommand in
        sparse-checkout | filter-repo | filter-branch) ;;
        clean)
            force=0
            while [ "$#" -gt 0 ]; do
                case $1 in
                    --) break ;;
                    --force | -*f*) force=1 ;;
                esac
                shift
            done
            [ "$force" -eq 1 ] || return 1
            ;;
        *) return 1 ;;
    esac

    [ "${NOHIKI_GIT_DESTRUCTIVE:-0}" = 1 ] && return 1

    top_level=$(
        cd "$probe_dir" 2>/dev/null || exit 1
        if [ "$have_git_dir" -eq 1 ]; then
            GIT_DIR=$probe_git_dir
            export GIT_DIR
        fi
        if [ "$have_work_tree" -eq 1 ]; then
            GIT_WORK_TREE=$probe_work_tree
            export GIT_WORK_TREE
        fi
        "$real_git" rev-parse --show-toplevel 2>/dev/null
    ) || return 1

    case $top_level in
        /tmp | /tmp/* | /private/tmp | /private/tmp/*) return 1 ;;
    esac

    [ -f "$top_level/flake.nix" ] &&
        [ -f "$top_level/lefthook.yml" ] &&
        [ -d "$top_level/proto/nohiki" ] || return 1

    return 0
}

if should_refuse "$@"; then
    printf "git-guard: refusing 'git %s' in Nohiki checkout %s\n" "$subcommand" "$top_level" >&2
    printf 'git-guard: set NOHIKI_GIT_DESTRUCTIVE=1 to override\n' >&2
    exit 2
fi

exec "$real_git" "$@"
