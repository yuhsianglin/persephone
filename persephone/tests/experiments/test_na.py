import os
from os.path import join
from pathlib import Path
import pytest
import subprocess

from persephone import corpus
from persephone import run
from persephone import corpus_reader
from persephone import rnn_ctc
from persephone.context_manager import cd
from persephone.datasets import na

EXP_BASE_DIR = "testing/exp/"
DATA_BASE_DIR = "testing/data/"

# TODO This needs to be uniform throughout the package and have a single point
# of control, otherwise the test will break when I change it elswhere. Perhaps
# it should have a txt extension.
TEST_PER_FN = "test/test_per" 

def set_up_base_testing_dir():
    """ Creates a directory to store corpora and experimental directories used
    in testing. """

    if not os.path.isdir(EXP_BASE_DIR):
        os.makedirs(EXP_BASE_DIR)
    if not os.path.isdir(DATA_BASE_DIR):
        os.makedirs(DATA_BASE_DIR)

def rm_dir(path: Path):

    import shutil
    if path.is_dir():
        shutil.rmtree(str(path))

def download_example_data(example_link):
    """
    Clears DATA_BASE_DIR, collects the zip archive from example_link and unpacks it into
    DATA_BASE_DIR.
    """

    # Prepare data and exp dirs
    set_up_base_testing_dir()
    zip_fn = join(DATA_BASE_DIR, "data.zip")
    if os.path.exists(zip_fn):
        os.remove(zip_fn)

    # Fetch the zip archive
    import urllib.request
    urllib.request.urlretrieve(example_link, filename=zip_fn)

    # Unzip the data
    import subprocess
    args = ["unzip", zip_fn, "-d", DATA_BASE_DIR]
    subprocess.run(args, check=True)

def get_test_ler(exp_dir):
    """ Gets the test LER from the experiment directory."""

    test_per_fn = join(exp_dir, TEST_PER_FN)
    with open(test_per_fn) as f:
        ler = float(f.readlines()[0].split()[-1])

    return ler

@pytest.mark.experiment
def test_tutorial():
    """ Tests running the example described in the tutorial in README.md """

    # 1024 utterance sample set.
    NA_EXAMPLE_LINK = "https://cloudstor.aarnet.edu.au/plus/s/YJXTLHkYvpG85kX/download"
    na_example_dir = join(DATA_BASE_DIR, "na_example/")
    rm_dir(Path(na_example_dir))

    download_example_data(NA_EXAMPLE_LINK)

    # Test the first setup encouraged in the tutorial
    corp = corpus.ReadyCorpus(na_example_dir)
    exp_dir = run.train_ready(corp, directory=EXP_BASE_DIR)

    # Assert the convergence of the model at the end by reading the test scores
    ler = get_test_ler(exp_dir)
    assert ler < 0.3

def test_fast():
    """
    A fast integration test that runs 1 training epoch over a tiny
    dataset. Note that this does not run ffmpeg to normalize the WAVs since
    Travis doesn't have that installed. So the normalized wavs are included in
    the feat/ directory so that the normalization isn't run.
    """

    # 4 utterance toy set
    TINY_EXAMPLE_LINK = "https://cloudstor.aarnet.edu.au/plus/s/g2GreDNlDKUq9rz/download"
    tiny_example_dir = join(DATA_BASE_DIR, "tiny_example/")
    rm_dir(Path(tiny_example_dir))

    download_example_data(TINY_EXAMPLE_LINK)

    corp = corpus.ReadyCorpus(tiny_example_dir)

    exp_dir = run.prep_exp_dir(directory=EXP_BASE_DIR)
    model = run.get_simple_model(exp_dir, corp)
    model.train(min_epochs=2, max_epochs=5)

    # Assert the convergence of the model at the end by reading the test scores
    ler = get_test_ler(exp_dir)
    # Can't expect a decent test score but just check that there's something.
    assert ler < 2.0

@pytest.mark.skip(reason="Refactoring has broken the na.Corpus interface, so"\
                         " this needs to be fixed. Also, Na-specific tests"\
                         " should go in a separate module anyway.")
@pytest.mark.experiment
def test_full_na():
    """ A full Na integration test. """

    # Pulls Na wavs from cloudstor.
    NA_WAVS_LINK = "https://cloudstor.aarnet.edu.au/plus/s/LnNyNa20GQ8qsPC/download"
    download_example_data(NA_WAVS_LINK)

    na_dir = join(DATA_BASE_DIR, "na/")
    os.rm_dir(na_dir)
    os.makedirs(na_dir)
    org_wav_dir = join(na_dir, "org_wav/")
    os.rename(join(DATA_BASE_DIR, "na_wav/"), org_wav_dir)
    tgt_wav_dir = join(na_dir, "wav/")

    NA_REPO_URL = "https://github.com/alexis-michaud/na-data.git"
    with cd(DATA_BASE_DIR):
        subprocess.run(["git", "clone", NA_REPO_URL, "na/xml/"], check=True)
    # Note also that this subdirectory only containts TEXTs, so this integration
    # test will include only Na narratives, not wordlists.
    na_xml_dir = join(DATA_BASE_DIR, "na/xml/TEXT/F4")

    label_dir = join(DATA_BASE_DIR, "na/label")
    label_type = "phonemes_and_tones"
    na.prepare_labels(label_type,
        org_xml_dir=na_xml_dir, label_dir=label_dir)

    tgt_feat_dir = join(DATA_BASE_DIR, "na/feat")
    # TODO Make this fbank_and_pitch, but then I need to install kaldi on ray
    # or run the tests on GPUs on slug or doe.
    feat_type = "fbank"
    na.prepare_feats(feat_type,
                     org_wav_dir=org_wav_dir,
                     tgt_wav_dir=tgt_wav_dir,
                     feat_dir=tgt_feat_dir,
                     org_xml_dir=na_xml_dir,
                     label_dir=label_dir)

    from shutil import copyfile
    copyfile("persephone/tests/test_sets/valid_prefixes.txt",
             join(na_dir, "valid_prefixes.txt"))
    copyfile("persephone/tests/test_sets/test_prefixes.txt",
             join(na_dir, "test_prefixes.txt"))
    na.make_data_splits(label_type, train_rec_type="text", tgt_dir=na_dir)

    # Training with texts
    exp_dir = run.prep_exp_dir(directory=EXP_BASE_DIR)
    na_corpus = na.Corpus(feat_type, label_type,
                          train_rec_type="text",
                          tgt_dir=na_dir)
    na_corpus_reader = corpus_reader.CorpusReader(na_corpus)
    model = rnn_ctc.Model(exp_dir, na_corpus_reader,
                                     num_layers=3, hidden_size=400)

    model.train(min_epochs=30)

    # Ensure LER < 0.20
    ler = get_test_ler(exp_dir)
    assert ler < 0.2

@pytest.mark.skip(reason="Refactoring has broken the na.Corpus interface, so"\
                         " this needs to be fixed. Also, Na-specific tests"\
                         " should go in a separate module anyway.")
@pytest.mark.experiment
def test_na_preprocess():
    """ Tests that the construction of the na.Corpus object works."""

    # TODO Only test_tutorial really needs to actually pull the data each time.
    # The other tests, including this one, can check if the data is already in
    # the (normal) data dir and only pull it if needed. Currently this test
    # just assumes it is there.

    # Prepare data and exp dirs
    set_up_base_testing_dir()
    tgt_dir = Path(DATA_BASE_DIR) / "na"
    tgt_dir.mkdir(exist_ok=True)

    from shutil import copyfile
    copyfile("persephone/tests/test_sets/valid_prefixes.txt",
             str(tgt_dir / "valid_prefixes.txt"))
    copyfile("persephone/tests/test_sets/test_prefixes.txt",
             str(tgt_dir / "test_prefixes.txt"))

    na_corpus = na.Corpus(feat_type="fbank", label_type="phonemes", tgt_dir=tgt_dir)
    assert len(na_corpus.get_train_fns()[0]) == 3092
    assert len(na_corpus.get_valid_fns()[0]) == 294
    assert len(na_corpus.get_test_fns()[0]) == 293

# Other tests:
    # TODO assert the contents of the prefix files

    # TODO Assert that we've filtered files with too many frames

    # TODO Test out corpus reader on the same data. (Make a function for that
    # within this functions scope)
