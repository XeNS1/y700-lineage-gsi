#!/usr/bin/env python3
"""Read the tablet's stock vendor CIL and link it with newly built GSI policy.

No tablet writes or flashing. Uses the user's Android-built secilc and the same
policy-link options as Android init. Prevents testing a policy with unresolved
stock-private symbols. Does not replace boot/hardware verification.
"""
import argparse
import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess

def command(args):
    return subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
def adb_read(prefix,path,required=True):
    # exec-out does not return the remote command's exit status. Its stream can
    # contain a cat error, which the old reader mistakenly saved as CIL. Shell
    # v2 with no PTY preserves file bytes and separates stderr/remote status.
    result=command(prefix+['shell','-T','cat',path])
    if result.returncode:
        error=result.stderr or result.stdout
        # Only a confirmed ENOENT from cat makes an optional file absent.
        # Permission errors and broken ADB connections must not silently pass.
        missing=re.fullmatch(rb'cat: '+re.escape(path.encode())+
          rb': No such file or directory\s*',error.strip())
        if not required and missing:
            print('Optional stock file absent:',path)
            return None
        detail=error.decode('utf-8',errors='replace').strip()
        raise ValueError('Cannot read from tablet: '+path+
          ' (ADB exit '+str(result.returncode)+')'+(': '+detail if detail else ''))
    if not result.stdout:
        if required: raise ValueError('Empty required tablet file: '+path)
        return None
    return result.stdout

def adb_cil(prefix,path,required=True):
    payload=adb_read(prefix,path,required)
    if payload is None: return None
    # Check just the first non-comment token; secilc still validates the full
    # syntax. Never strip or rewrite the original policy bytes.
    first=next((line.strip() for line in payload.splitlines()
                if line.strip() and not line.lstrip().startswith(b';')),b'')
    if first and not first.startswith(b'('):
        raise ValueError('Tablet file is not CIL: '+path+
          ': '+first[:160].decode('utf-8',errors='replace'))
    return payload

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('project',type=Path)
    parser.add_argument('--product-out',type=Path,required=True)
    parser.add_argument('--secilc',type=Path,help='Host compiler built in the same OUT_DIR')
    parser.add_argument('--serial')
    args=parser.parse_args()
    project=args.project.resolve();product=args.product_out.resolve()
    if shutil.which('adb') is None: raise ValueError('adb not found; connect TB321FU before this check')
    serial=args.serial
    if not serial:
        result=command(['adb','devices'])
        devices=[line.split()[0] for line in result.stdout.decode().splitlines()[1:]
                 if len(line.split())==2 and line.split()[1]=='device']
        if len(devices)!=1: raise ValueError('Connect one TB321FU or pass --serial')
        serial=devices[0]
    adb=['adb','-s',serial]
    for key,wanted in {
      'ro.product.vendor.device':'TB321FU',
      'ro.vendor.build.version.incremental':'TB321FU_CN_OPEN_USER_Q00011.0_V_ZUI_17.0.10.138_ST_250626',
    }.items():
        value=command(adb+['shell','getprop',key]).stdout.decode().strip()
        if value!=wanted: raise ValueError('Tablet does not match the tested stock base: '+key)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    work=project/'inputs/features/bypass/native-policy-check'/stamp;work.mkdir(parents=True)
    vendor=adb_cil(adb,'/vendor/etc/selinux/vendor_sepolicy.cil')
    if not re.search(rb'\(type\s+vendor_sysfs_battery_supply\)',vendor):
        raise ValueError('Stock policy does not declare the known vendor battery type')
    version=adb_read(adb,'/vendor/etc/selinux/plat_sepolicy_vers.txt').decode().strip()
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',version): raise ValueError('Unexpected vendor policy version')
    (work/'vendor_sepolicy.cil').write_bytes(vendor)
    stock=[]
    for path,required in [('/vendor/etc/selinux/plat_pub_versioned.cil',True),('/odm/etc/selinux/odm_sepolicy.cil',False)]:
        payload=adb_cil(adb,path,required)
        if payload is not None:
            dst=work/Path(path).name;dst.write_bytes(payload);stock.append(dst)
    # Android init links plat_pub_versioned before vendor/odm. Keep that order.
    stock.insert(1,work/'vendor_sepolicy.cil')
    genfs_raw=adb_read(adb,'/vendor/etc/selinux/genfs_labels_version.txt',False)
    try:
        genfs_version=int(genfs_raw.decode().strip()) if genfs_raw is not None else 202404
        if not -(2**31)<=genfs_version<2**31: genfs_version=202404
    except (ValueError,UnicodeError):
        genfs_version=202404
    policies=[]
    def add(path,required=True):
        if path.is_file(): policies.append(path)
        elif required: raise ValueError('Build policy file missing: '+str(path))
    platform=product/'system/etc/selinux/plat_sepolicy.cil'
    if not platform.is_file(): raise ValueError('Build platform policy is missing: '+str(platform))
    variants=[('normal',platform)]
    system_ext_roots=[product/'system_ext/etc/selinux',product/'system/system_ext/etc/selinux']
    debug=next((root/'userdebug_plat_sepolicy.cil' for root in system_ext_roots
                if (root/'userdebug_plat_sepolicy.cil').is_file()),None)
    if debug is not None: variants.append(('gsi-userdebug',debug))
    for label,path in variants:
        content=path.read_text()
        if 'y700_bypassd' not in content or 'y700_bypass_stock_vendor' not in content:
            raise ValueError('Platform variant '+label+' is missing the feature; rebuild selinux_policy')
    add(product/f'system/etc/selinux/mapping/{version}.cil')
    add(product/f'system/etc/selinux/mapping/{version}.compat.cil',False)
    for part in ['system_ext','product']:
        roots=[product/part/'etc/selinux',product/'system'/part/'etc/selinux']
        existing=next((root for root in roots if root.is_dir()),None)
        if existing is not None:
            add(existing/(part+'_sepolicy.cil'),False)
            add(existing/f'mapping/{version}.cil',False)
            if part=='system_ext': add(existing/f'mapping/{version}.compat.cil',False)
    add(product/f'system/etc/selinux/plat_sepolicy_genfs_{genfs_version}.cil',False)
    tools=[project/'out/gsi-vanilla-ext4/host/linux-x86/bin/secilc',
           project/'source/out/host/linux-x86/bin/secilc']
    compiler=args.secilc.resolve() if args.secilc is not None else next((path for path in tools if path.is_file()),None)
    if compiler is None: raise ValueError('Android-built host secilc not found')
    # Same link options as Android init. -N ignores neverallow checks while linking
    # old stock vendor rules. This does not change the product's existing
    # SELINUX_IGNORE_NEVERALLOWS setting, mark a domain permissive or change
    # the device's enforcement mode.
    results=[]
    for label,path in variants:
        argv=[str(compiler),str(path),'-m','-M','true','-G','-c','30','-N',
              *map(str,policies),*map(str,stock),'-o',str(work/('linked-stock-policy-'+label)),
              '-f',str(work/('linked-file-contexts-'+label))]
        result=command(argv)
        log=work/('secilc-'+label+'.log'); log.write_bytes(result.stdout+result.stderr)
        results.append({'variant':label,'platform_policy':str(path),'exit_code':result.returncode,'log':str(log)})
    (work/'result.json').write_text(json.dumps({'serial':serial,'vendor_policy_version':version,
      'platform_policies':[str(path) for path in policies],'stock_policies':[str(path) for path in stock],
      'genfs_labels_version':genfs_version,'variants':results,
      'enforcing_changed':False},ensure_ascii=False,indent=2)+'\n')
    if any(result['exit_code'] for result in results):
        raise ValueError('Stock/GSI policy link failed; see '+str(work/'result.json'))
    print('PASS: new GSI policy links with stock vendor/odm; Enforcing unchanged.')
    print('Result:',work/'result.json')

if __name__=='__main__':
    try: main()
    except (ValueError,OSError) as error: raise SystemExit('Error: '+str(error))
