#!/usr/bin/env python3
#
# (C) 2019 by Jose M. Guisado <jmgg@riseup.net>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""
Generate files containing nftables geoip mappings and definitions.

This script is intended to be executed and not imported.
"""

from collections import namedtuple
from datetime import datetime

import argparse
import csv
import gzip
import ipaddress
import os
import requests
import shutil
import sys
import time
import unicodedata

DEFAULT_FILE_LOCATION = 'location.csv'
DEFAULT_FILE_ADDRESS = 'dbip.csv'

# entries in location csv
GeoEntry = namedtuple('GeoEntry',
                      'name, '
                      'alpha_2, '
                      'alpha_3, '
                      'country_code, '
                      'iso_3166_2, '
                      'region, '
                      'sub_region, '
                      'intermediate_region, '
                      'region_code, '
                      'sub_region_code, '
                      'intermediate_region_code')

# entries in DB-IP geoip csv
NetworkEntry = namedtuple('NetworkEntry',
                          'network_first, '
                          'network_last, '
                          'country_alpha_2')


class DownloadAction(argparse.BooleanOptionalAction):
    """
    Custom BooleanOptionalAction to download db-ip csv in case the user
    specified so.
    """
    def __call__(self, parser, namespace, values, option_string=None):
        super().__call__(parser, namespace, values, option_string=option_string)
        if namespace.download:
            # Add trailing / for folder path if there is none
            namespace.dir += '/' if namespace.dir[-1:] != '/' else ''
            filename = namespace.dir+'dbip.csv.gz'
            url = 'https://download.db-ip.com/free/dbip-country-lite-{}.csv.gz'.format(time.strftime("%Y-%m"))
            print('Downloading db-ip.com geoip csv file...')
            r = requests.get(url, stream=True)
            if r.status_code == 200:
                with open(filename, 'wb') as f:
                    r.raw.decode_content = True
                    shutil.copyfileobj(r.raw, f)
            else:
                sys.exit('Error trying to download DB-IP lite geoip csv file. Bailing out...')

            with gzip.open(filename, 'rb') as f_in:
                with open(namespace.dir+'dbip.csv', 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
                    os.remove(filename)
            # Update blocks arg with the downloaded file
            setattr(namespace, 'blocks', open(namespace.dir+'dbip.csv', 'r', encoding='utf-8'))

def strip_accent(text):
    """
    Remove accented characters. Convert to ASCII.
    """
    return ''.join(char for char in unicodedata.normalize('NFKD', text)
                   if unicodedata.category(char) != 'Mn')


def make_location_dicts():
    """
    Returns three formatted dictionaries with following key/value:
        - iso_3166_2 (numeric)  :   country name
        - country_name          :   continent/region name
        - country_name          :   alpha2 name
    """
    country_dict = {}
    continent_dict = {}
    country_alpha_dict = {}
    next(args.locations)  # Omit license notice
    next(args.locations)  # Omit csv header
    for geo_entry in map(GeoEntry._make, csv.reader(args.locations)):
        country_name = normalize(geo_entry.name)
        country_dict[normalize(geo_entry.country_code.lstrip('0'))] = country_name
        continent_dict[country_name] = normalize(geo_entry.region)
        country_alpha_dict[country_name] = normalize(geo_entry.alpha_2)
    return country_dict, continent_dict, country_alpha_dict


def normalize(value):
    """
    Strip accents and replace special characters.

    Used for keys and values inside location dictionaries.
    """
    return strip_accent(value).lower().replace(' ', '_').replace('[', '').replace(']', '').replace(',', '')


def write_geoip_location(country_dict, continent_dict, country_alpha_dict):
    """
    Write country iso code definitions, separating files for each continent
    (eg. geoip-def-asia.nft, etc.)
    Also writes a definition file with all countries in "geoip-def-all.nft"
    """
    for continent in continent_dict.values():
        with open(args.dir+'geoip-def-{}.nft'.format(continent), 'w') as output_file:
            try:
               for country, iso in [(country, iso)
                                    for iso, country
                                    in country_dict.items()
                                    if continent_dict[country] == continent]:
                    output_file.write('define {} = {}\n'.format(country_alpha_dict[country].upper(), iso))
            except KeyError as e:
                # 'ZZ' is used for an unknown country, so it won't match
                # any country in the location file. Pass and do not write
                # to output file
                pass

    with open(args.dir+'geoip-def-all.nft', 'w') as output_file:
        for iso, country in country_dict.items():
            output_file.write('define {} = {}\n'.format(country_alpha_dict[country].upper(), iso))
        output_file.write('\n' * 2)

        output_file.write('define africa = 1\n'
                          'define asia = 2\n'
                          'define europe = 3\n'
                          'define americas = 4\n'
                          'define oceania = 5\n'
                          'define antarctica = 6\n')
        output_file.write('\n')
        output_file.write('map continent_code {\n'
                          '\ttype mark : mark\n'
                          '\tflags interval\n'
                          '\telements = {\n\t\t')

        output_file.write(',\n\t\t'.join(make_lines2({country_alpha_dict[country].upper():v
                                                      for country, v
                                                      in continent_dict.items()})))
        output_file.write('\n')
        output_file.write('\t}\n')
        output_file.write('}\n')


def check_ipv4(addr):
    """
    Returns true if a string is representing an ipv4 address.
    False otherwise.
    """
    try:
        ipaddress.IPv4Address(addr)
        return True
    except ipaddress.AddressValueError:
        return False


def make_geoip_dict(country_alpha_dict):
    """
    Read DB-IP network ranges and creates geoip4 and geoip6 dictionaries
    mapping ip ranges over country alpha-2 codes
    """
    # XXX: country_alpha_dict is used to prune countries not appearing
    #      inside location.csv (eg. Kosovo)
    #
    #      Kosovo could be added to location.csv with a "virtual" code
    #      Kosovo,XK,XKX,999,ISO 3166-2:XK,Europe,"","","","",""
    #
    #      Or instead use geonames.
    geoip4_dict = {}
    geoip6_dict = {}

    known_alphas = country_alpha_dict.values()

    # Reset file object position to start of the address file
    args.blocks.seek(0)

    for net_entry in map(NetworkEntry._make, csv.reader(args.blocks)):

        alpha2 = net_entry.country_alpha_2.lower()
        # 'ZZ' or codes not appearing in location.csv will be ignored
        if (alpha2 == 'zz') or (alpha2 not in known_alphas):
            continue

        # There are entries in DB-IP csv for single addresses which
        # are represented as same start and end address range.
        # nftables does not accept same start/end address in ranges
        if net_entry.network_first == net_entry.network_last:
            k = net_entry.network_first
        else:
            k = '-'.join((net_entry.network_first, net_entry.network_last))

        if check_ipv4(net_entry.network_first):
            geoip4_dict[k] = alpha2
        else:
            geoip6_dict[k] = alpha2

    return geoip4_dict, geoip6_dict


def make_lines1(dictionary):
    """
    For each entry in the dictionary maps to a line for nftables dict files
    using key literal and value as nft variable.
    """
    return ['{} : ${}'.format(k, v) for k, v in dictionary.items()]


def make_lines2(dictionary):
    """
    For each entry in the dictionary maps to a line for nftables dict files
    using key and value as nft variables.
    """
    return ['${} : ${}'.format(k, v) for k, v in dictionary.items()]


def write_nft_header(f):
    """
    Writes nft comments about generation date and db-ip copyright notice.
    """
    f.write("# Generated by nft_geoip.py on {}\n"
            .format(datetime.now().strftime("%a %b %d %H:%M %Y")))
    f.write("# IP Geolocation by DB-IP (https://db-ip.com) licensed under CC-BY-SA 4.0\n\n")


def write_geoip_maps(geoip4_dict, geoip6_dict, interesting=False):
    """
    Write ipv4 and ipv6 geoip nftables maps to corresponding output files.
    """
    ipv4_file = 'geoip-ipv4-interesting.nft' if interesting else 'geoip-ipv4.nft'
    ipv6_file = 'geoip-ipv6-interesting.nft' if interesting else 'geoip-ipv6.nft'
    with open(args.dir+ipv4_file, 'w') as output_file:
        write_nft_header(output_file)
        output_file.write('map geoip4 {\n'
                          '\ttype ipv4_addr : mark\n'
                          '\tflags interval\n'
                          '\telements = {\n\t\t')

        output_file.write(',\n\t\t'.join(make_lines1({k:v.upper() for k,v in geoip4_dict.items()})))
        output_file.write('\n')
        output_file.write('\t}\n')
        output_file.write('}\n')

    with open(args.dir+ipv6_file, 'w') as output_file:
        write_nft_header(output_file)
        output_file.write('map geoip6 {\n'
                          '\ttype ipv6_addr : mark\n'
                          '\tflags interval\n'
                          '\telements = {\n\t\t')

        output_file.write(',\n\t\t'.join(make_lines1({k:v.upper() for k,v in geoip6_dict.items()})))
        output_file.write('\n')
        output_file.write('\t}\n')
        output_file.write('}\n')


def create_parser():
    """
    Returns cli argument parser
    """
    parser = argparse.ArgumentParser(description=__doc__,
                                     prog='nft_geoip')
    parser.add_argument('--file-location',
                        type=argparse.FileType('r'),
                        help='path to csv file containing information about countries. '
                            f'(default: {DEFAULT_FILE_LOCATION})',
                        default=DEFAULT_FILE_LOCATION,
                        required=False,
                        dest='locations')
    parser.add_argument('--file-address',
                        type=argparse.FileType('r'),
                        help='path to db-ip.com lite cvs file with ipv4 and ipv6 geoip information '
                            f'(default: {DEFAULT_FILE_ADDRESS})',
                        required=False,
                        dest='blocks')
    parser.add_argument('-d', '--download', action=DownloadAction,
                        help='Fetch geoip data from db-ip.com. Overrides --file-address.',
                        default=False,
                        required=False)
    parser.add_argument('-o', '--output-dir',
                        help='Existing directory where downloads and output will be saved. '
                             '(default: working directory)',
                        default='./',
                        required=False,
                        dest='dir')
    parser.add_argument('-c', '--country-filter,',
                        help='Comma-separated list of countries to create a filtered nft map (e.g. us,ca,gb). '
                              'Accepts full name or abbrevation (see --show-countries)',
                        required=False,
                        dest='countries')
    parser.add_argument('--show-countries', action='store_true',
                        help='Show a list of countries to be provided to --country-filter.',
                        required=False)
    return parser


if __name__ == '__main__':
    parser = create_parser()
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        parser.print_help()
        sys.exit('\nSpecified output directory does not exist or is not a directory')
    else:
        # Add trailing / for folder path if there isn't
        args.dir += '/' if args.dir[-1:] != '/' else ''

    if not (args.blocks or args.locations):
        parser.print_help()
        sys.exit('Missing required address and location csv files.')
    if not args.blocks:
        parser.print_help()
        sys.exit('Missing geoip address csv file. You can instead download it using --download.')
    if not args.locations:
        parser.print_help()
        sys.exit('Missing country information csv file')

    country_dict, continent_dict, country_alpha_dict = make_location_dicts()

    if args.show_countries:
        for k, v in country_alpha_dict.items():
            print("Country: {} ({})".format(k,v))
        sys.exit(0)

    print('Writing country definition files...')
    write_geoip_location(country_dict, continent_dict, country_alpha_dict)
    print('Writing nftables maps (geoip-ipv{4,6}.nft)...')
    geoip4_dict, geoip6_dict = make_geoip_dict(country_alpha_dict)
    write_geoip_maps(geoip4_dict, geoip6_dict)

    # Write separate map of countries if list provided
    if (args.countries):
        countries = list(map(str.lower,args.countries.split(',')))
        interesting_countries = {k: v for k, v in country_alpha_dict.items() if k in countries or v in countries}
        if len(interesting_countries) > 0:
            print('Found countries: ', interesting_countries)
            print('Writing interesting countries file...')
            interesting_countries_ipv4, interesting_countries_ipv6  = make_geoip_dict(interesting_countries)
            write_geoip_maps(interesting_countries_ipv4, interesting_countries_ipv6, True)
        else:
            print('Skipping interesting countries output, no matching countries found')

    print('Done!')
