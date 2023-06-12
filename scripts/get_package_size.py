import requests

## This function is useful for estimating the size of a package and check if it is small enough for your lambda function
def get_package_total_size(package_name):
    url = f'https://pypi.org/pypi/{package_name}/json'
    response = requests.get(url)
    
    if response.status_code == 200:
        package_info = response.json()
        latest_version = package_info['info']['version']
        files = package_info['releases'][latest_version]
        
        total_size = sum(file['size'] for file in files[:1])
        print(f"Total size of {package_name} (latest version {latest_version}): {total_size/1e6} MB")
    else:
        print(f"Unable to fetch package information for {package_name}. Status code: {response.status_code}")

get_package_total_size('GitPython')