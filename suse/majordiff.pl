#!/usr/bin/perl
# Copyright 2026 SUSE LLC <georg.pfuetzenreuter@suse.com>
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

use v5.26;

use File::Temp 'tempfile';

my %pairs_old;
my %pairs_new;

my $cmd1 = "git -P log --grep 'core: bump' --invert-grep --oneline --no-merges --pretty='%h %s' --reverse version/2025.12.4..suse-main";
my $cmd2 = "git -P logf --committer='Georg Pfuetzenreuter' --pretty='%h %s' suse-2025.12..suse-2026.2";

open (my $fh1, '-|', $cmd1) or die "Failed to run: $cmd1";

while (my $line = <$fh1>) {
	my ($hash, $msg) = split(' ', $line, 2);
	$pairs_old{$msg} = $hash;
}

close($fh1);

open (my $fh2, '-|', $cmd2) or die "Failed to run: $cmd2";

while (my $line = <$fh2>) {
	my ($hash, $msg) = split(' ', $line, 2);
	$pairs_new{$msg} = $hash;
}

close($fh2);

for (keys %pairs_old) {
	my $msg = $_;
	my $hash_old = $pairs_old{$msg};
	if (! exists $pairs_new{$msg}) {
		print "Commit dropped: $hash_old - $msg\n";
		next;
	}
	my $hash_new = $pairs_new{$msg};

	print "Commit rebased: $hash_old => $hash_new - $msg\n";
	# abusing range-diff would be nice but diff context is off
	system("git -P range-diff --creation-factor=100 $hash_old^..$hash_old $hash_new^..$hash_new");

	#my ($fh_old, $file_old) = tempfile("majordiff_$hash_old" . "_XXXX", TMPDIR => 1, UNLINK => 1);
	#my ($fh_new, $file_new) = tempfile("majordiff_$hash_new" . "_XXXX", TMPDIR => 1, UNLINK => 1);

	#print $fh_old `git show --format= -U0 $hash_old`;
	#print $fh_new `git show --format= -U0 $hash_new`;

	#close($fh_old);
	#close($fh_new);

	#system("interdiff --color=always -U0 $file_old $file_new");

	#unlink($file_old);
	#unlink($file_new);
};
