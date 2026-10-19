"""Download one pinned Desklib snapshot, including tokenizer and provenance."""
import argparse
import hashlib
import json
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download
from localtext.config import get_models_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default='main', help='Upstream commit or ref; resolved once to a commit')
    parser.add_argument('--destination', type=Path, default=get_models_dir() / 'desklib')
    args = parser.parse_args()
    repo = 'desklib/ai-text-detector-v1.01'
    commit = HfApi().model_info(repo, revision=args.revision).sha
    print(f'Downloading {repo}@{commit} to {args.destination} (approximately 1.8 GB).')
    snapshot_download(repo, revision=commit, local_dir=args.destination,
                      allow_patterns=['*.json', '*.model', '*.txt', 'model.safetensors', 'README.md'])
    for name in ['config.json', 'model.safetensors']:
        if not (args.destination / name).is_file():
            raise RuntimeError(f'Missing required file: {name}')
    hashes = {}
    for path in sorted(args.destination.iterdir()):
        if path.is_file() and path.name != 'localtext-manifest.json':
            with path.open('rb') as stream:
                hashes[path.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    manifest = {'repository': repo, 'commit': commit, 'sha256': hashes}
    (args.destination / 'localtext-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Download complete. Select this folder in GUI Settings. Accuracy is not locally validated.')


if __name__ == '__main__':
    main()
