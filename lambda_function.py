import json
import boto3
import os
import time
s3_client = boto3.client('s3', region_name='us-east-2')
ssm_client = boto3.client('ssm', region_name='us-east-2')
ec2_client = boto3.client('ec2', region_name='us-east-2')


def get_ecs_optimized_ami():
    # created a function to get latest ECS Optimizes image using SSM
    # Parameter name to fetch the recommended ECS optimized AMI
    parameter_name = '/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended'
    
    try:
        # Fetch the parameter value
        response = ssm_client.get_parameters(
            Names=[parameter_name],
            WithDecryption=False  # Set to True if the parameter is encrypted
        )
        
        # Extract the parameter value from the response
        if 'Parameters' in response and response['Parameters']:
            parameter_value = response['Parameters'][0]['Value']
            recommended_ami = json.loads(parameter_value)  # Parse the JSON string
            return recommended_ami
        else:
            raise Exception("No parameter value found for {}".format(parameter_name))
            return ""
    except Exception as e:
        print("No parameter value found for {}".format(e))
        return ""
        
        
def create_s3_bucket(bucket_name):
    
    #created function to create s3 bucket.
    try:
        # Check if the bucket already exists
        response = s3_client.head_bucket(Bucket=bucket_name)
        print("S3 Bucket {} already exists".format(bucket_name))
        
    except s3_client.exceptions.ClientError as e:
        error_code = int(e.response['Error']['Code'])
        if error_code == 404:
            # Creates the bucket as it does not exist
            response = s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={
                    'LocationConstraint': 'us-east-2'  # Specify your desired region
                }
            )
            print("S3 Bucket {} created successfully".format(bucket_name))
            return True
        else:
            print("Exception while creating  S3: {}".format(e))
    return False

def upload_file_to_s3(bucket_name, file_name):
    res = create_s3_bucket(bucket_name)
    if not res:
        return False
    try:
        # Upload the file to S3
        with open(file_name, 'rb') as f:
            response = s3_client.put_object(
                Bucket=bucket_name,
                Key=file_name.split("/")[-1],
                Body=f
            )
        print("Uploaded file {} to S3 bucket {}".format(file_name,bucket_name))
        
    except Exception as e:
        print("Exception while uploading file to S3: {}".format(file_name))
        return False
    return True

def lambda_handler(event, context):
    executed = True
    instance_ids =[]
    Bucket_list =[]
    try:
        # Get the latest ECS-optimized Amazon Linux 2 AMI ID
        recommended_ami = get_ecs_optimized_ami()
        if recommended_ami == "":
            executed = False
        
        latest_ami_id = recommended_ami["image_id"]
        try:
            max_instance = int(os.environ['max_instance']) # initialised to create 10 instances 
            for i in range(max_instance):
                instance_name = os.environ['instance_name']+str(i+1)
                s3_bucket_name = os.environ['s3_bucket_name']+str(i+1)
                # Launch EC2 instance
                instance = ec2_client.run_instances(
                    ImageId=latest_ami_id,
                    InstanceType=os.environ['InstanceType'],
                    
                    SecurityGroupIds=[
                        os.environ['SecurityGroupIds']
                    ],
                    SubnetId=os.environ['SubnetId'],  #  subnet ID in Ohio (us-east-2)
                    
                    MinCount=1,
                    MaxCount=1,
                    TagSpecifications=[
                        {
                            'ResourceType': 'instance',
                            'Tags': [
                                {'Key': 'Name', 'Value': instance_name}  
                            ]
                        }
                    ]
                )
                
                instance_id = instance['Instances'][0]['InstanceId']
                instance_ids.append(instance_id)
                print("Launched EC2 instance {}".format(instance_id))
                filename ="/tmp/"+instance_name+".txt"
                with open(filename, 'w') as f:
                    f.write(instance_id)
                    f.close()
                response = upload_file_to_s3(s3_bucket_name, filename)
                if not response:
                    executed = False
                Bucket_list.append(s3_bucket_name)
                time.sleep(50) #   issue while creating more than 3 instances as CPU limit is crossed, so added sleep just to check
        except Exception as e:
            print(f"Exception while creating the instance: {e}")        
            executed = False
    
    except Exception as e:
        print("Exception: {}",format(e))
        executed = False
    if not executed:
        return {
            'statusCode': 500,
            'body': json.dumps("Execution Failed")
        }
    else:
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': "Successfully launched {} EC2 instances.".format(len(instance_ids)),
                'instance_ids': instance_ids,
                'Bucket_ids':Bucket_list
            })
        }
