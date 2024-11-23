import boto3
import json
import os
import base64
import requests

def lambda_handler(event, context):
    try:
        # イベント全体をログに出力
        print("Received event:", json.dumps(event, indent=2))

        # リクエストボディの解析
        body = event.get('body', None)
        if not body:
            raise ValueError("Request body is missing")

        # JSON形式の確認と解析
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("Request body is not a valid JSON")

        # キー名を 'prompt' に修正
        user_input = body.get('prompt', '')
        if not user_input:
            return {
                'statusCode': 400,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                },
                'body': json.dumps({'error': 'No input provided'})
            }

        # Bedrockに渡すリクエストボディの作成
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": (
                        f"ユーザー入力: {user_input}\n"
                        "以下のルールに基づいてTerraformコードを生成してください。\n"
                        "variableにstringでaws_access_key_idとaws_secret_access_keyを定義し、providerブロックに記述する。\n"
                        "providerを記述し、東京リージョンとする。\n"
                        "terraform ブロックは不要。\n"
                        "terraformのコードのみを出力し、出力ファイルの前後に不要なテキストは含めない。\n"
                        "```の囲い込みは含めない。\n"
                        "記述しなくても設定が変わらないパラメータは記述しない。\n"
                        "Terraform名にAWSサービス名は含めない。\n"
                        "Terraform名の出力に迷ったら deploy と出力する。\n"
                        "各リソースの接続に必要なリソースブロックは適宜補完する。\n"
                        "タグ名はすべてdeploy-サービス名とする。\n"
                        "EC2のAMIは ami-03f584e50b2d32776 に固定し、コメントは「AL2023」と出力する。\n"
                        "EC2はSSHキー hiyama-diagram を設定する。\n"
                        "EC2にはパブリックIPを付与する。\n"
                        "EC2はセキュリティグループを設定し、SSH通信のみを許可する。\n"
                        "ingressの cidr_blocks = ['0.0.0.0/0'] には コメント 「# 適宜変更」を追加する。\n"
                        "セキュリティグループのegressの設定は不要。\n"
                        "S3を作成するときは最低限のコードだけでよい\n"
                    )}
                ]
            }]
        }

        # Bedrockモデルの呼び出し
        bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
        response_body = bedrock.invoke_model(
            modelId='us.anthropic.claude-3-5-sonnet-20241022-v2:0',
            contentType='application/json',
            accept='application/json',
            body=json.dumps(request_body)
        )['body'].read().decode('utf-8')

        # レスポンスからTerraformコードを取得
        terraform_code = next((c['text'] for c in json.loads(response_body).get('content', []) if c['type'] == 'text'), None) or json.dumps(response_body)

        # GitHubにコードをアップロード
        repo_name, github_token, branch_name = os.environ['GITHUB_REPO'], os.environ['GITHUB_TOKEN'], 'develop'
        api_url = f'https://api.github.com/repos/{repo_name}/contents/main.tf'
        headers = {'Authorization': f'token {github_token}', 'Content-Type': 'application/json'}
        
        # ファイルのSHAを取得し、ファイルを更新または作成
        sha = requests.get(api_url, headers=headers, params={'ref': branch_name}).json().get('sha')
        create_or_update_data = {
            "message": "Add generated Terraform code from Bedrock",
            "content": base64.b64encode(terraform_code.encode('utf-8')).decode('utf-8'),
            "sha": sha, "branch": branch_name
        } if sha else {
            "message": "Add generated Terraform code from Bedrock",
            "content": base64.b64encode(terraform_code.encode('utf-8')).decode('utf-8'),
            "branch": branch_name
        }
        requests.put(api_url, headers=headers, data=json.dumps(create_or_update_data))

        # プルリクエストを作成
        pr_data = {"title": "Merge develop into main", "head": branch_name, "base": "main", "body": "This PR merges the generated Terraform code into the main branch."}
        pr_url = f"https://api.github.com/repos/{repo_name}/pulls"
        pr_response = requests.post(pr_url, headers=headers, data=json.dumps(pr_data))

        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Origin': '*',
            },
            'body': json.dumps('File successfully pushed and pull request created' if pr_response.status_code in [200, 201] else 'Failed to create pull request')
        }

    except Exception as e:
        # エラーをログ出力
        print(f"Error: {e}")
        return {
            'statusCode': 500,
            'headers': {
                'Access-Control-Allow-Origin': '*',
            },
            'body': json.dumps({'error': str(e)})
        }
