{pkgs ? import <nixpkgs> {}}:
pkgs.mkShell rec {
  buildInputs = [
    pkgs.python310
    pkgs.poetry
    pkgs.zlib
    pkgs.stdenv.cc.cc
    pkgs.python310Packages.tensorboard
  ];
  LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath buildInputs;
}
